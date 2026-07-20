import os

from PIL import Image, ImageDraw, ImageFont, ImageOps
import requests, base64
from utils import random_utils
import logging

def create_picture_frame_2x2(img_path):
    # Open the frame image and the four images to insert
    frame_image = Image.open("./output/base_frame.jpg")
    photo_path1 = random_utils.random_file_from_folder(img_path)
    photo_path2 = random_utils.random_file_from_folder(img_path)
    photo_path3 = random_utils.random_file_from_folder(img_path)
    photo_path4 = random_utils.random_file_from_folder(img_path)

    image1 = Image.open(photo_path1)
    image2 = Image.open(photo_path2)
    image3 = Image.open(photo_path3)
    image4 = Image.open(photo_path4)

    # Define the dimensions and positions of the four cells in the frame
    cell_width = frame_image.width // 2  # Assuming the frame is divided into 2 columns
    cell_height = frame_image.height // 2  # Assuming the frame is divided into 2 rows
    cell_positions = [(0, 0), (cell_width, 0), (0, cell_height), (cell_width, cell_height)]

    # Resize the images to fit the cells
    # image1.w, image1.h = image1.size
    # print(image1.w, image1.h)
    # image1 = image1.resize((image1.width//2, image1.height//2))
    # image1 = image1.resize((cell_width, cell_height))
    # image2 = image2.resize((cell_width, cell_height))
    # image3 = image3.resize((cell_width, cell_height))
    # image4 = image4.resize((cell_width, cell_height))

    # Add a white border around each image
    border_width = 3
    image1 = ImageOps.expand(image1, border=border_width, fill="white")
    image2 = ImageOps.expand(image2, border=border_width, fill="white")
    image3 = ImageOps.expand(image3, border=border_width, fill="white")
    image4 = ImageOps.expand(image4, border=border_width, fill="white")

    # Paste each image onto the corresponding cell in the frame
    for image, position in zip([image1, image2, image3, image4], cell_positions):
        frame_image.paste(image, position)

    # Create a semi-transparent black overlay for the last cell
    overlay_width, overlay_height = cell_width, cell_height
    overlay_image = Image.new("RGBA", (overlay_width, overlay_height), (0, 0, 0, 128))  # Semi-transparent black overlay

    # Paste the overlay onto the last cell
    last_cell_position = cell_positions[-1]
    frame_image.paste(overlay_image, last_cell_position, overlay_image)

    # Add overlay with the number 8 in the center of the last cell
    last_cell_position = cell_positions[-1]
    overlay_image = Image.new("RGBA", (cell_width, cell_height), (255, 255, 255, 0))  # Create transparent overlay
    draw = ImageDraw.Draw(overlay_image)
    font = ImageFont.truetype("./fonts/arial.ttf", size=40)  # Adjust font size as needed
    random_number = random_utils.random_number()
    text =  f"+{random_number}" #"+15"
    text_width = draw.textlength(text, font, font_size=40)
    text_height = draw.textlength(text, font, font_size=40)
    text_position = ((cell_width - text_width) // 2, (cell_height - text_height) // 2)
    draw.text(text_position, text, fill="white", font=font, align="center")
    frame_image.paste(overlay_image, last_cell_position, overlay_image)
    # save image
    frame_image.save("./output/output.jpg")


def create_picture_frame_2x3(img_path):
    # Open the frame image and the four images to insert
    frame_image = Image.open("./output/base_frame.jpg")
    photo_path1 = random_utils.random_file_from_folder(img_path)
    photo_path2 = random_utils.random_file_from_folder(img_path)
    photo_path3 = random_utils.random_file_from_folder(img_path)
    photo_path4 = random_utils.random_file_from_folder(img_path)

    image1 = Image.open(photo_path1)
    image2 = Image.open(photo_path2)
    image3 = Image.open(photo_path3)
    image4 = Image.open(photo_path4)


    # Define the dimensions and positions of the four cells in the frame
    # cell_width = frame_image.width // 2  # Assuming the frame is divided into 2 columns
    base_height = frame_image.height // 3
    base_width = frame_image.width // 3
    image1 = ImageOps.fit(image1, (base_width*2, frame_image.height))
    image2 = ImageOps.fit(image2, (400,400))
    image3 = ImageOps.fit(image3, (400,400))
    image4 = ImageOps.fit(image4, (400,400))

    
    cell_positions = [(0, 0), (base_width*2, 0), (base_width*2, base_height), (base_width*2, base_height*2)]

    # Add a white border around each image
    border_width = 3
    image1 = ImageOps.expand(image1, border=border_width, fill="white")
    image2 = ImageOps.expand(image2, border=border_width, fill="white")
    image3 = ImageOps.expand(image3, border=border_width, fill="white")
    image4 = ImageOps.expand(image4, border=border_width, fill="white")

    # Paste each image onto the corresponding cell in the frame
    for image, position in zip([image1, image2, image3, image4], cell_positions):
        frame_image.paste(image, position)
        frame_image.save("./output/output.jpg")

    # Create a semi-transparent black overlay for the last cell
    overlay_width, overlay_height = base_width*2, base_height*2
    overlay_image = Image.new("RGBA", (overlay_width, overlay_height), (0, 0, 0, 128))  # Semi-transparent black overlay

    # Paste the overlay onto the last cell
    last_cell_position = cell_positions[-1]
    frame_image.paste(overlay_image, last_cell_position, overlay_image)

    # Add overlay with the number in the center of the last cell
    last_cell_position = cell_positions[-1]
    overlay_image = Image.new("RGBA", (base_width*2, base_height*2), (255, 255, 255, 0))  # Create transparent overlay
    draw = ImageDraw.Draw(overlay_image)

    
    font = ImageFont.truetype("./fonts/arial.ttf", size=40)  # Adjust font size as needed
    # random_number = random_utils.random_number()
    # text =  f"+{random_number}" 
    text = "SEE MORE.."
    text_width = draw.textlength(text, font, font_size=40)
    text_height = draw.textlength(text, font, font_size=40)
    text_position = ((base_width - text_width) // 2, (base_height - text_height))
    draw.text(text_position, text, fill="white", font=font, align="center")
    frame_image.paste(overlay_image, last_cell_position, overlay_image)
    # save image
    frame_image.save("./output/output.jpg")
    # frame_image.show()


def create_picture_frame_3x2(img_path):
    # Open the frame image and the four images to insert
    frame_image = Image.open("./output/base_frame.jpg")
    photo_path1 = random_utils.random_file_from_folder(img_path)
    photo_path2 = random_utils.random_file_from_folder(img_path)
    photo_path3 = random_utils.random_file_from_folder(img_path)
    photo_path4 = random_utils.random_file_from_folder(img_path)

    image1 = Image.open(photo_path1)
    image2 = Image.open(photo_path2)
    image3 = Image.open(photo_path3)
    image4 = Image.open(photo_path4)


    # Define the dimensions and positions of the four cells in the frame
    # cell_width = frame_image.width // 2  # Assuming the frame is divided into 2 columns
    base_height = frame_image.height // 3
    base_width = frame_image.width // 3
    image1 = image1.resize((frame_image.width, base_height*2))
    image2 = crop_center(image2, 400,400)
    image3 = crop_center(image3, 400,400)
    image4 = crop_center(image4, 400,400)


    # set static size instead
    # import ipdb; ipdb.set_trace()
    # image1 = image1.resize((base_width*2, frame_image.height))
    # image2 = image2.resize((base_width, base_height))
    # image3 = image3.resize((base_width, base_height))
    # image4 = image4.resize((base_width, base_height))
    
    cell_positions = [(0, 0), (0, base_height*2), (base_width, base_height*2),(base_width*2, base_height*2)]

    # Add a white border around each image
    border_width = 3
    image1 = ImageOps.expand(image1, border=border_width, fill="white")
    image2 = ImageOps.expand(image2, border=border_width, fill="white")
    image3 = ImageOps.expand(image3, border=border_width, fill="white")
    image4 = ImageOps.expand(image4, border=border_width, fill="white")

    # Paste each image onto the corresponding cell in the frame
    for image, position in zip([image1, image2, image3, image4], cell_positions):
        frame_image.paste(image, position)
        frame_image.save("./output/output.jpg")

    # Create a semi-transparent black overlay for the last cell
    overlay_width, overlay_height = base_width*2, base_height*2
    overlay_image = Image.new("RGBA", (overlay_width, overlay_height), (0, 0, 0, 128))  # Semi-transparent black overlay

    # Paste the overlay onto the last cell
    last_cell_position = cell_positions[-1]
    frame_image.paste(overlay_image, last_cell_position, overlay_image)

    # Add overlay with the number in the center of the last cell
    last_cell_position = cell_positions[-1]
    overlay_image = Image.new("RGBA", (base_width*2, base_height*2), (255, 255, 255, 0))  # Create transparent overlay
    draw = ImageDraw.Draw(overlay_image)

    
    font = ImageFont.truetype("./fonts/arial.ttf", size=40)  # Adjust font size as needed
    random_number = random_utils.random_number()
    text =  f"+{random_number}" #"+15"
    text_width = draw.textlength(text, font, font_size=40)
    text_height = draw.textlength(text, font, font_size=40)
    text_position = ((base_width - text_width) // 2, (base_height - text_height) // 2)
    draw.text(text_position, text, fill="white", font=font, align="center")
    frame_image.paste(overlay_image, last_cell_position, overlay_image)
    # save image
    frame_image.save("./output/output.jpg")
    # frame_image.show()


def crop_center(image, width, height):
    img_width, img_height = image.size
    left = (img_width - width) // 2
    top = (img_height - height) // 2
    right = (img_width + width) // 2
    bottom = (img_height + height) // 2
    return image.crop((left, top, right, bottom))


def create_picture_frame_5x3(img_path):
    # Open the frame image and the four images to insert
    frame_image = Image.open("./output/base_frame.jpg")
    photo_path1 = random_utils.random_file_from_folder(img_path)
    photo_path2 = random_utils.random_file_from_folder(img_path)
    photo_path3 = random_utils.random_file_from_folder(img_path)
    photo_path4 = random_utils.random_file_from_folder(img_path)
    photo_path5 = random_utils.random_file_from_folder(img_path)


    image1 = Image.open(photo_path1)
    image2 = Image.open(photo_path2)
    image3 = Image.open(photo_path3)
    image4 = Image.open(photo_path4)
    image5 = Image.open(photo_path5)



    # Define the dimensions and positions of the four cells in the frame
    # cell_width = frame_image.width // 2  # Assuming the frame is divided into 2 columns
    base_height = frame_image.height // 3
    base_width = frame_image.width // 3
    image1 = ImageOps.fit(image1, (frame_image.width//2, base_height*2))
    image2 = ImageOps.fit(image2, (frame_image.width//2, base_height*2))

    image3 = ImageOps.fit(image3, (400,400))
    image4 = ImageOps.fit(image4, (400,400))
    image5 = ImageOps.fit(image5, (400,400))
    
    
    cell_positions = [(0, 0), (frame_image.width//2, 0), (0, base_height*2), (base_width, base_height*2), (base_width*2, base_height*2)]

    # Add a white border around each image
    border_width = 3
    image1 = ImageOps.expand(image1, border=border_width, fill="white")
    image2 = ImageOps.expand(image2, border=border_width, fill="white")
    image3 = ImageOps.expand(image3, border=border_width, fill="white")
    image4 = ImageOps.expand(image4, border=border_width, fill="white")
    image5 = ImageOps.expand(image5, border=border_width, fill="white")

    # Paste each image onto the corresponding cell in the frame
    for image, position in zip([image1, image2, image3, image4, image5], cell_positions):
        frame_image.paste(image, position)
        frame_image.save("./output/output.jpg")
        # frame_image.show()

    # Create a semi-transparent black overlay for the last cell
    overlay_width, overlay_height = base_width*2, base_height*2
    overlay_image = Image.new("RGBA", (overlay_width, overlay_height), (0, 0, 0, 128))  # Semi-transparent black overlay

    # Paste the overlay onto the last cell
    last_cell_position = cell_positions[-1]
    frame_image.paste(overlay_image, last_cell_position, overlay_image)

    # Add overlay with the number in the center of the last cell
    last_cell_position = cell_positions[-1]
    overlay_image = Image.new("RGBA", (base_width*2, base_height*2), (255, 255, 255, 0))  # Create transparent overlay
    draw = ImageDraw.Draw(overlay_image)

    
    font = ImageFont.truetype("./fonts/arial.ttf", size=40)  # Adjust font size as needed
    # test disable random_number
    # random_number = random_utils.random_number()
    text =  "SEE MORE.." #"+15"
    text_width = draw.textlength(text, font, font_size=40)
    text_height = draw.textlength(text, font, font_size=40)
    text_position = ((base_width - text_width) // 2, (base_height - text_height))
    draw.text(text_position, text, fill="white", font=font, align="center")
    frame_image.paste(overlay_image, last_cell_position, overlay_image)
    # save image
    frame_image.save("./output/output.jpg")
    # frame_image.show()



def create_picture_frame_3x5(img_path):
    # Open the frame image and the four images to insert
    frame_image = Image.open("./output/base_frame.jpg")
    photo_path1 = random_utils.random_file_from_folder(img_path)
    photo_path2 = random_utils.random_file_from_folder(img_path)
    photo_path3 = random_utils.random_file_from_folder(img_path)
    photo_path4 = random_utils.random_file_from_folder(img_path)
    photo_path5 = random_utils.random_file_from_folder(img_path)


    image1 = Image.open(photo_path1)
    image2 = Image.open(photo_path2)
    image3 = Image.open(photo_path3)
    image4 = Image.open(photo_path4)
    image5 = Image.open(photo_path5)



    # Define the dimensions and positions of the four cells in the frame
    # cell_width = frame_image.width // 2  # Assuming the frame is divided into 2 columns
    base_height = frame_image.height // 3
    base_width = frame_image.width // 3
    image4 = image4.resize((frame_image.width//2, base_height*2))
    image5 = image5.resize((frame_image.width//2, base_height*2))
    image3 = crop_center(image3, 400,400)
    image1 = crop_center(image1, 400,400)
    image2 = crop_center(image2, 400,400)
    # import ipdb; ipdb.set_trace()


    # set static size instead
    # image1 = image1.resize((base_width*2, frame_image.height))
    # image2 = image2.resize((base_width, base_height))
    # image3 = image3.resize((base_width, base_height))
    # image4 = image4.resize((base_width, base_height))
    
    cell_positions = [(0, 0), (base_width, 0), (base_width*2, 0), (0, base_height), (frame_image.width//2,base_height)]

    # Add a white border around each image
    border_width = 3
    image1 = ImageOps.expand(image1, border=border_width, fill="white")
    image2 = ImageOps.expand(image2, border=border_width, fill="white")
    image3 = ImageOps.expand(image3, border=border_width, fill="white")
    image4 = ImageOps.expand(image4, border=border_width, fill="white")
    image5 = ImageOps.expand(image5, border=border_width, fill="white")
    # Paste each image onto the corresponding cell in the frame
    for image, position in zip([image1, image2, image3, image4, image5], cell_positions):
        frame_image.paste(image, position)
        frame_image.save("./output/output.jpg")
        # frame_image.show()
    # Create a semi-transparent black overlay for the last cell
    overlay_width, overlay_height = base_width*2, base_height*2
    overlay_image = Image.new("RGBA", (overlay_width, overlay_height), (0, 0, 0, 128))  # Semi-transparent black overlay

    # Paste the overlay onto the last cell
    last_cell_position = cell_positions[-1]
    frame_image.paste(overlay_image, last_cell_position, overlay_image)

    # Add overlay with the number in the center of the last cell
    last_cell_position = cell_positions[-1]
    overlay_image = Image.new("RGBA", (base_width*2, base_height*2), (255, 255, 255, 0))  # Create transparent overlay
    draw = ImageDraw.Draw(overlay_image)

    
    font = ImageFont.truetype("./fonts/arial.ttf", size=40)  # Adjust font size as needed
    # random_number = random_utils.random_number()
    # test disable random_number
    # text =  f"+{random_number}" #"+15"
    text =  "SEE MORE.." #"+15"
    text_width = draw.textlength(text, font, font_size=40)
    text_height = draw.textlength(text, font, font_size=40)
    text_position = ((frame_image.width //2  - text_width) // 2, ((frame_image.height - base_height) - text_height) // 1.5)
    draw.text(text_position, text, fill="white", font=font, align="center")
    frame_image.paste(overlay_image, last_cell_position, overlay_image)
    # save image
    frame_image.save("./output/output.jpg")
    # frame_image.show()


def image_to_base64(image_path):
    with open(image_path, "rb") as image_file:
        # Read the image file as binary data
        image_data = image_file.read()
    
    # Encode the binary data as Base64
    base64_encoded = base64.b64encode(image_data).decode("utf-8")
    return base64_encoded


def upload_picture(img_file):
    img_base64 = image_to_base64(img_file)
    imgbb_api_key = os.environ.get("IMGBB_API_KEY")
    if not imgbb_api_key:
        raise RuntimeError("IMGBB_API_KEY must be configured to upload to imgbb")
    api_url = "https://api.imgbb.com/1/upload"

    payload = {
        "key": imgbb_api_key,
        "image": img_base64
        }
    response = requests.post(api_url, data=payload).json()
    uploaded_url = response['data']['url']
    logging.info("uploaded_url " + uploaded_url)

    return uploaded_url

def upload_self_hosted_picture(img_file):
    tmp_img_name = str(random_utils.random_img_name())
    url = os.environ.get("AUTOFB_IMAGE_UPLOAD_URL")
    token = os.environ.get("AUTOFB_IMAGE_UPLOAD_TOKEN")
    if not url or not token:
        raise RuntimeError("AUTOFB_IMAGE_UPLOAD_URL and AUTOFB_IMAGE_UPLOAD_TOKEN must be configured")
    headers = {
        'Accept': 'application/json',
        'x-token': token,
    }
    with open(img_file, 'rb') as image:
        response = requests.post(
            url,
            headers=headers,
            files={'file': (f"{tmp_img_name}.jpg", image, 'image/jpeg')},
            timeout=60,
        )
    response.raise_for_status()
    return response.json()['image_url']
