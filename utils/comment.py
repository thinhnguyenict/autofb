import requests
import pandas as pd


def random_comment_from_excel(excel_file):
    # Read the Excel file into a DataFrame
    df = pd.read_excel(excel_file)
    
    # Sample a random row from the DataFrame
    random_row = df.sample(n=1)
    # Get the message and link from the random row
    message = random_row["message"].values[0]
    link = random_row["link"].values[0]

    return message, link



def comment_on_post(post_id, message, link, access_token):
    url = f"https://graph.facebook.com/v25.0/{post_id}/comments"
    params = {
        "message": f"[You may like] {message}: {link}",
        "access_token": access_token
    }
    response = requests.post(url, params=params, timeout=60)
    if response.status_code == 200:
        print("Comment posted successfully.")
    else:
        print("Error posting comment:", response.json())

# message, link = random_comment_from_excel("./data.xlsx")
# comment_on_post("471948829668444_890934523046722", message, link, "EAAOZCt57jvjsBOZCabpiKsseXAQcUXdQ7acBV1xsjTZABZCFVWjRu4FO0vZACJpKjehvGtjsHtFIHvgPJIlngCx2ZArHLnp7O6kRQVXxvZCdLcoVSzyJzWVeLhctfa1zSlNhI8q6ih441EfmBkGxYM1I0mCm6VOwhbdxMzbWPG3JSYosIAPHRSQNRWZAoZBjCKE4m")
