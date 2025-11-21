import pandas as pd

# Loop over each row in the DataFrame
def read_excel(file):
    # Read the Excel file into a DataFrame
    df = pd.read_excel(file)
    messages = []
    links = []
    paths = []
    cell_indexes = []
    for index, row in df.iterrows():
        # Get the values of the columns
        message = row["message"]
        link = row["link"]
        path = row["path"]
        publish_status = row["publish_status"]
        if publish_status.lower() == "no":
            messages.append(message)
            links.append(link)
            paths.append(path)
            cell_indexes.append(index)
    # print(messages, links, paths, cell_index)
    return messages, links, paths, cell_indexes


def update_publish_status(file, index):
    df = pd.read_excel(file)
    print("index:" + str(index))
    df.at[index, "publish_status"] = "AAA"
    df.to_excel("data.xlsx", index=False)



# messages, links, paths, cell_index = read_excel("./data.xlsx")
# print( messages, links, paths, cell_index)
# update_publish_status("./data.xlsx", 1)