import random, os
import pandas as pd

def random_file_from_folder(folder_path):
    try:
        if not os.path.exists(folder_path) or not os.path.isdir(folder_path):
            raise ValueError("Invalid folder path")
        files = [f for f in os.listdir(folder_path) if os.path.isfile(os.path.join(folder_path, f))]
        if not files:
            raise ValueError("No files found in the folder")
        random_file = random.choice(files)
        return os.path.join(folder_path, random_file)
    except Exception as e:
        print(f"Error: {e}")
        return None


def random_emoticon():
    emoticons = ["😄", "😊", "😍", "🌞", "🌈", "🌸", "💖", "🌟", "🎉", "💐", "🌺", "🌷", "💓", "😇", "🌼", "😁", "💫", "💗", "😎", "💕", "🍃"]
    chosen_emoticon = random.choice(emoticons)
    return chosen_emoticon

def random_number():
    return random.randint(20, 60)


def random_caption(excel_file):
    # Read the Excel file into a DataFrame
    df = pd.read_excel(excel_file)
    
    # Sample a random row from the DataFrame
    random_row = df.sample(n=1)
    # Get the message and link from the random row
    caption = random_row["caption"].values[0]
    # print(caption)
    return caption

# random_caption("../caption.xlsx")

def random_img_name():
    return random.randint(0, 6000000)