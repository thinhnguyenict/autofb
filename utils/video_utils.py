import requests
import logging

token = "EAAQDiDJQJmoBO3AY3mDjnUCRRZBz7JVv7ENBx4nrJxKGQ9hLfcDekgizS2wSOzTZAkpKZAgEmRL6ZA5Fz33V5L7T4ymtH8mCJ7cg4FW2AhnafNbKYKPE3gUKBuZADdQ0QG4LD4pIT7qkvFBRJ36zgky6G8GwGW0WBQo7V7syl7cNwhMsSesRFgAW9CzYqONTzdqhLPDGk0ZB8cBZCEZD"
page = "235216366656147 "
video_path = "/root/autopost-tiny/videos/353592089980175.mp4"

logging.basicConfig(
    format='%(asctime)s %(levelname)s:%(message)s',
    level=logging.INFO)

def upload_video(page_id, access_token, video):
    # api url
    url = f"https://rupload.facebook.com/video-upload/v21.0/{page_id}/video_reels"
    video = open(video, 'rb')
    logging.debug(video)

    files = {
        'data': video
    }

    payload = {
        "title": "Title - I love you 3000",
        "description":  "Desc: I love you 3000",
        "access_token": access_token
    }

    response = requests.post(url, files=files, data=payload).json()
    logging.info(response)

upload_video(page, token, video_path)