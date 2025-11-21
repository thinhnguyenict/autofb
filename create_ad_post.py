import json, random, logging
from utils import picture_utils, ad_post_utils

logging.basicConfig(
    format='%(asctime)s %(levelname)s:%(message)s',
    level=logging.INFO)

with open('./config.json') as f:
    config = json.load(f)

excel_file = config['excel']['path']
access_token = config['pages']['access_token']
page_id = config['pages']['page_id']
page_name = config['pages']['page_name']
act_id = config['pages']['act_id']


def main():
    for page, name, token in zip(page_id, page_name, access_token):
        print(page, name, token)
        
        # random link for each page
        # fetch content from prepared excel file
        try:
            message, link, img_path, cell_index = ad_post_utils.read_excel(excel_file)
            print (message, link, img_path, cell_index)
        except TypeError:
            print(f"All posts are  published. \nPlease prepare the data again. File path: {excel_file}")
            quit()

        # TODO: choose types
        # functions = [picture_utils.create_picture_frame_2x2, picture_utils.create_picture_frame_2x3, picture_utils.create_picture_frame_3x2, picture_utils.create_picture_frame_5x3, picture_utils.create_picture_frame_3x5]
        functions = [picture_utils.create_picture_frame_5x3, picture_utils.create_picture_frame_2x3]
        # functions = [picture_utils.create_picture_frame_5x3]

        selected_function = random.choice(functions)
        print("Func: " + str(selected_function))
        selected_function(img_path)

        # img_url = picture_utils.upload_picture(img_file="/output/output.jpg")
        img_url = picture_utils.upload_self_hosted_picture(img_file="./output/output.jpg")
        logging.info("img_url " + img_url)


        # get ad post id and publish post
        ad_post_data = json.loads(ad_post_utils.create_ad_post(img_url, message, link, page, token, act_id))
        ad_post_id = ad_post_data["id"]

        import time; time.sleep(40) #wait till the post can be fetched from facebook (fb workflow)
        effective_object_story_id = ad_post_utils.get_ad_effective_object_story_id(ad_post_id, token)
        print(effective_object_story_id)
        ad_post_utils.publish_ad_post(token, effective_object_story_id)
        ad_post_utils.update_publish_status(excel_file, cell_index)
        print(f"Done publishing post to {name} page")

if __name__ ==  "__main__":
    main()

