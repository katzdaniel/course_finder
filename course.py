import modal

app = modal.App("course_finder")

image = modal.Image.debian_slim().pip_install_from_requirements("requirements.txt")

modal_secrets = modal.Secret.from_name("course_finder_secrets")

@app.function(image=image, secrets=[modal_secrets])
def fetch_data():
    import requests
    import os
    url = 'https://oracle-www.dartmouth.edu/dart/groucho/timetable.display_courses'
    data = {
        'distribradio': 'alldistribs',
        'depts': ['no_value', 'COSC'],
        'periods': 'no_value',
        'distribs': 'no_value',
        'distribs_i': 'no_value',
        'distribs_wc': 'no_value',
        'distribs_lang': 'no_value',
        'deliveryradio': 'alldelivery',
        'deliverymodes': 'no_value',
        'pmode': 'public',
        'term': '',
        'levl': '',
        'fys': 'n',
        'wrt': 'n',
        'pe': 'n',
        'review': 'n',
        'crnl': 'no_value',
        'classyear': '2008',
        'searchtype': 'Subject Area(s)',
        'termradio': 'selectterms',
        'terms': ['no_value', '202409'],
        'subjectradio': 'selectsubjects',
        'hoursradio': 'allhours',
        'sortorder': 'dept'
    }

    proxies = {
        'http': os.getenv('PROXY_URL'),
        'https': os.getenv('PROXY_URL'),
    }
    # print('proxy url: ', os.getenv('PROXY_URL'))
    
    response = requests.post(url, data=data, proxies=proxies)
    return response

@app.function(image=image, secrets=[modal_secrets])
def extract_class_information(html_content):
    """
    Extracts class information from the provided HTML content.

    Args:
        html_content (str): The HTML content as a string.

    Returns:
        List[Dict]: A list of dictionaries containing class information.
    """
    from lxml import html

    # Parse the HTML content
    tree = html.fromstring(html_content)

    # Find the data table
    data_table = tree.xpath('//div[@class="data-table"]/table')[0]

    # Extract headers
    headers = [th.text_content().strip() for th in data_table.xpath('.//th')]

    # Initialize list to hold class information
    class_info_list = []

    # Extract all <td> elements within the table
    td_elements = data_table.xpath('.//td')

    # Since the HTML is not well-structured with <tr> tags for each row,
    # we will group every set of cells that correspond to the number of headers
    num_columns = len(headers)
    row_data = []
    for td in td_elements:
        text = td.text_content().strip()
        # Handle nested links and images
        if td.xpath('.//a'):
            text = td.xpath('.//a')[0].text_content().strip()
        elif td.xpath('.//img'):
            text = td.xpath('.//img')[0].get('src', '').strip()

        row_data.append(text)

        # Once we've collected data for one row, add it to the list
        if len(row_data) == num_columns:
            class_info = dict(zip(headers, row_data))
            class_info_list.append(class_info)
            row_data = []

    return class_info_list

@app.function(image=image, secrets=[modal_secrets])
def find_row_by_crn(table_element, crn):
    """
    Finds and returns the table row that contains the specified CRN.

    Parameters:
    - table_element: The lxml element representing the table.
    - crn: The CRN string to search for.

    Returns:
    - The lxml element representing the matching table row, or None if not found.
    """
    from lxml import html

    # Iterate over all rows in the table
    for row in table_element.xpath('.//tr'):
        # Find all cells in the row
        cells = row.xpath('.//td')
        for cell in cells:
            # Check if the cell text matches the CRN
            if cell.text_content().strip() == crn:
                # Return the row if a matching CRN is found
                return row
    # Return None if no matching row is found
    return None

@app.function(image=image, secrets=[modal_secrets])
def is_class_full(class_info):
    """
    Checks if a class is full based on the enrollment and limit.

    Parameters:
    - class_info: A dictionary containing class information.

    Returns:
    - Boolean: True if the class is full, False otherwise.
    """
    try:
        enrl = int(class_info.get('Enrl', '0'))
        lim = int(class_info.get('Lim', '0'))
        return enrl >= lim
    except ValueError:
        # If we can't convert to integers, assume the class is full
        return True

@app.function(image=image, secrets=[modal_secrets])
def send_email(class_info):
    """
    Sends an email to the user if the class is not full.

    Parameters:
    - class_info: A dictionary containing class information.
    """
    import resend
    import os

    resend.api_key = os.environ["RESEND_API_KEY"]

    course_name = class_info.get('Title')
    course_crn = class_info.get('CRN')
    instructor = class_info.get('Instructor')
    enrl = class_info.get('Enrl')
    lim = class_info.get('Lim')

    subject = f'{course_name} has an opening; CRN: {course_crn}'
    html = f'''<strong>{course_name} with {instructor} has an opening.\n\n
    The CRN: {course_crn}.</strong>\n\n
    There are {enrl} students enrolled and the limit is {lim}.

    '''

    params = resend.Emails.SendParams = {
        "from": "DK Personal Email <me@personal.emails.katzdaniel.com>",
        "to": ["daniel.nmn.katz@gmail.com"],
        "subject": subject,
        "html": html,
    }

    resend.Emails.send(params)

    print('email sent')
    

@app.function(image=image, secrets=[modal_secrets])
def run_process():
    response = fetch_data.local()
    class_info_list = extract_class_information.local(response.text)
    # table = extract_table(response.text)
    # row = find_row_by_crn(table, '91714')
    # print(response.text)
    # for class_info in class_info_list:
    #     print(class_info)
    # Find the class with CRN 91714
    target_crn = '91714'
    target_class = next((class_info for class_info in class_info_list if class_info.get('CRN') == target_crn), None)
    
    if target_class:
        # print(f"\nClass with CRN {target_crn}:")
        # for key, value in target_class.items():
        #     print(f"{key}: {value}")
        print(target_class)
    else:
        print(f"\nNo class found with CRN {target_crn}")

    if not is_class_full.local(target_class):
        send_email.remote(target_class)


# The cron job will run every 5 minutes from 6:00 AM to 7:55 PM ET, Monday through Friday.
@app.function(schedule=modal.Cron("*/5 10-23 * * MON-FRI"))
def entry1():
    run_process.spawn()

# The cron job will run every 5 minutes from 8:00 PM to 1:55 AM ET, Monday evening through Saturday morning.
@app.function(schedule=modal.Cron("*/5 0-5 * * TUE-SAT"))
def entry2():
    run_process.spawn()

@app.local_entrypoint()
def main():
    run_process.remote()