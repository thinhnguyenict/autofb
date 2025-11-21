 - create token for each pages (though have same admin)
 1. get token user (with permissions) from https://developers.facebook.com/tools/explorer/1055220295777851/?method=GET&path=me%3Ffields%3Did%2Cname&version=v19.0

 2. to get short lived token
 appID=1055220295777851
 appSecret=c1b527f83264f379bd44618ebc60dc20
 short_token=EAAOZCt57jvjsBO7HNhCQRvCWb5dBgDPiJRRnOXCv8Cu87nEu5RrL0RphXKkQBLDxYX22LK3bn2U3pD3wg7BNyPbKCAuerEDZCs5e45OJT3KganLtoIRCV2zSM1dYCDAQQZAxvnokgjnLYToOY91cQzeXZC4aV5VCiQ5bgpJcZCi4zi7CCSOQDeI9GcvfeRu8i2vBvnr1gEQk2pQNn9AZDZD

 curl https://graph.facebook.com/v19.0/oauth/access_token?grant_type=fb_exchange_token&client_id=1055220295777851&client_secret=c1b527f83264f379bd44618ebc60dc20&fb_exchange_token=EAAOZCt57jvjsBO7HNhCQRvCWb5dBgDPiJRRnOXCv8Cu87nEu5RrL0RphXKkQBLDxYX22LK3bn2U3pD3wg7BNyPbKCAuerEDZCs5e45OJT3KganLtoIRCV2zSM1dYCDAQQZAxvnokgjnLYToOY91cQzeXZC4aV5VCiQ5bgpJcZCi4zi7CCSOQDeI9GcvfeRu8i2vBvnr1gEQk2pQNn9AZDZD

3. get never expired token

curl https://graph.facebook.com/v19.0/me/accounts?access_token=EAAOZCt57jvjsBO0Ubo0RoUEUfcmtDMDc4oXX1ii6UryGvayeDUmsHDtqA84UM8TsI2S2wq3IhSf4nX0tsXIOlTTv14Yos38oLOZBUcvO3KXmDWjJJhfmuhbJ7qbMq9NzXNEaVgsDg7ZBdqZC63yZCXhZA8CbSMppZAg0FBd2GwXFOj1y2ZB934QjuxKh







GUIDELINE
To generate a long-lived Page access token for managing multiple pages as an admin through the Facebook Graph API, you can follow these steps:

Create a Facebook App:

Go to the Facebook Developers website.
Create a new app.
Note your App ID and App Secret.
Generate a Short-Lived User Token:

Use the Graph API Explorer tool.
Select your app from the top-right corner.
Click "Get Token" > "Get User Access Token."
Select the necessary permissions (e.g., manage_pages, publish_pages).
Click "Generate Access Token."
Extend the Token:

Open a browser and make a GET request to the following URL, replacing <app_id>, <app_secret>, and <short-lived-user-token> with your app's information:
php
Copy code
https://graph.facebook.com/v12.0/oauth/access_token?grant_type=fb_exchange_token&client_id=<app_id>&client_secret=<app_secret>&fb_exchange_token=<short-lived-user-token>
Retrieve the new long-lived token from the JSON response.
Get Page Access Tokens:

Make a GET request to the following URL to get a list of pages you manage:
vbnet
Copy code
https://graph.facebook.com/v12.0/me/accounts?access_token=<long-lived-user-token>
Retrieve the access_token for each page you want to manage.
Now, you have long-lived tokens for both the user and the pages. These tokens should be saved securely, and you can use them to manage your pages through the Graph API.

Keep in mind that access tokens have expiration periods, so you may need to handle token renewal if they expire. Additionally, make sure to handle tokens securely, as they grant access to sensitive information.




