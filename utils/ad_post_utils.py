import pandas as pd
import requests

DEFAULT_API_VERSION = "v25.0"
# Loop over each row in the DataFrame
# def read_excel(file):
#     try:
#         # Read the Excel file into a DataFrame
#         df = pd.read_excel(file)
#         messages = []
#         links = []
#         paths = []
#         cell_indexes = []
#         for index, row in df.iterrows():
#             # Get the values of the columns
#             message = row["message"]
#             link = row["link"]
#             path = row["path"]
#             publish_status = row["publish_status"]
#             if publish_status.lower() == "no":
#                 messages.append(message)
#                 links.append(link)
#                 paths.append(path)
#                 cell_indexes.append(index)
#     except TypeError:
#         print("Error: Unsupported operand type!")
#     return messages[0], links[0], paths[0], cell_indexes[0]

def read_excel(file):
        # Read the Excel file into a DataFrame
        df = pd.read_excel(file)
        message = ""
        link = ""
        path = ""

        for index, row in df.iterrows():
            try: 
                if row["publish_status"].lower() != "yes":
                    # Get the values of the columns
                    message = row["message"]
                    link = row["link"]
                    path = row["path"]
                    return message, link, path, index
            except TypeError:
                pass


def update_publish_status(file, index):
    df = pd.read_excel(file)
    print("index:" + str(index))
    df.at[index, "publish_status"] = "yes"
    df.to_excel(file, index=False)
    print("Successfully updated the publish status")


def create_ad_post(picture, message, link, page, access_token, act_id, api_version=DEFAULT_API_VERSION):
    # api url
    url = f"https://graph.facebook.com/{api_version}/{act_id}/adcreatives"

    # Define the payload data
    payload = {
        "object_story_spec": {
            "link_data": {
                "call_to_action": {"type":"LEARN_MORE"}, 
                "picture": picture,
                "link": link,
                "message": message,
                "description": "   ",
                "multi_share_optimized": True,
                "multi_share_end_card": False,
                "caption": "facebook.com",
                "name": "  "
            },
            "page_id": page,
            "link_caption": ""
        },
        "degrees_of_freedom_spec": {
            "creative_features_spec": {
                "standard_enhancements": {
                    "enroll_status": "OPT_IN"
                }
            }
        },
        # "call_to_action_type": "LEARN_MORE",
        "access_token": access_token
    }

    # Send the POST request
    # import ipdb; ipdb.set_trace()
    response = requests.post(url, json=payload, timeout=60)
    ad_post_id = response.text
    return ad_post_id


def get_ad_effective_object_story_id(ad_post_id, access_token, api_version=DEFAULT_API_VERSION):
    url = f'https://graph.facebook.com/{api_version}/{ad_post_id}'

    params = {
        'fields': 'effective_object_story_id',
        'access_token': access_token
    }
    response = requests.get(url=url, params=params, timeout=60)
    if response.status_code == 200:
        data = response.json()
        effective_object_story_id=data['effective_object_story_id']
        return  effective_object_story_id
    else:
        print(f"Error: {response.status_code}, {response.text}")
        return None


def publish_ad_post(access_token, effective_object_story_id, api_version=DEFAULT_API_VERSION):
    url = f'https://graph.facebook.com/{api_version}/{effective_object_story_id}'
    headers = {
    'accept': 'application/json, text/plain, */*',
    'content-type': 'application/json'
    }
    payload = {
        'is_published': True
    }
    params = {'access_token': access_token}
    response = requests.post(url=url, params=params, json=payload, headers=headers, timeout=60)
    # import ipdb; ipdb.set_trace()
    if response.status_code == 200:
        print(response.json())
    else:
        print(f"Error: {response.status_code}, {response.text}")
