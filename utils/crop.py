from PIL import Image, ImageDraw, ImageFont, ImageOps
import requests, base64
import random_utils



def crop_center(image, width, height):
    img_width, img_height = image.size
    left = (img_width - width) // 2
    top = (img_height - height) // 2
    right = (img_width + width) // 2
    bottom = (img_height + height) // 2
    return image.crop((left, top, right, bottom))



def create_picture_frame_5x3(img_path):
    # Open the frame image and the four images to insert
    frame_image = Image.open("../img/base_frame.jpg")
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
    image1 = image1.resize((frame_image.width//2, base_height*2), Image.LANCZOS)
    image2 = image2.resize((frame_image.width//2, base_height*2), Image.LANCZOS)
    import ipdb; ipdb.set_trace()
    image3 = crop_center(image3, 400,400)
    image4 = crop_center(image4, 400,400)
    image5 = crop_center(image5, 400,400)

create_picture_frame_5x3("../img")