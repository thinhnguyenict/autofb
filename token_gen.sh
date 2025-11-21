#!/bin/bash

short_token_gen() {
    export app_id="257272274104298"
    export app_secret="9c873c92b673dc1a27e5912d092e60b9"
    export fb_token="EAAOZCt57jvjsBOzY0s5o1rKgeIxPQ9ZBpKTfFu8qrZBMLVsfpN2MwzBb2Wr3lINsIU8e7RXTb9kdmpbsfiz2fhoibZCq7ZBi4oG5R8s7PJrvSyXwQlPU83pNUgSFI00ZCBzFCd0jXtkGEIkpoHG0sho0nPg6T80vWHp1vB08SBMH37vmA1iTZARJuILwSY3yVYPcDo7lyXImoglzLuuxlS1XDiep2Oc"
    curl https://graph.facebook.com/v19.0/oauth/access_token?grant_type=fb_exchange_token&client_id=257272274104298&client_secret=9c873c92b673dc1a27e5912d092e60b9&fb_exchange_token=EAAOZCt57jvjsBOyHZBEZBmtRid8v5EO4ByJpiHtJvyNI0r4WNZCTpckpmDVjTvwANmJKJOLve0XwZADDmySCzoZAx0aQNpCxroheoHZBq5coybKXHHF4pZAp1gZB3j2QInrsSXSTaOZBcZARAzTrynFZBnWAdOdmXvHgdce0rKZAZAaZATtUYpHYS6Yc5hQqrlWgIuVqPbmW7bGc1nBYdxth2KGwiqf8gWZC3uuq
}



> /Users/tuyentd/personal/huuthinh/autopost/utils/ad_post_utils.py(63)get_ad_effective_object_story_id()                                                                                           
     62     import ipdb; ipdb.set_trace()                                                                                                                                                          
---> 63     url = 'https://graph.facebook.com/v19.0/%s'  %ad_post_id                                                                                                                               
     64     params = {                                                                                                                                                                             
                                                                                                                                                                                                   
ipdb> n                                                                                                                                                                                            
> /Users/tuyentd/personal/huuthinh/autopost/utils/ad_post_utils.py(65)get_ad_effective_object_story_id()                                                                                           
     64     params = {                                                                                                                                                                             
---> 65         'fields': 'effective_object_story_id',                                                                                                                                             
     66         'access_token': access_token                                                                                                                                                       
                                                                                                                                                                                                   
ipdb> n                                                                                                                                                                                            
> /Users/tuyentd/personal/huuthinh/autopost/utils/ad_post_utils.py(66)get_ad_effective_object_story_id()                                                                                           
     65         'fields': 'effective_object_story_id',                                                                                                                                             
---> 66         'access_token': access_token                                                                                                                                                       
     67     }                                                                                                                                                                                      
                                                                                                                                                                                                   
ipdb> n                                                                                                                                                                                            
> /Users/tuyentd/personal/huuthinh/autopost/utils/ad_post_utils.py(64)get_ad_effective_object_story_id()                                                                                           
     63     url = 'https://graph.facebook.com/v19.0/%s'  %ad_post_id                                                                                                                               
---> 64     params = {                                                                                                                                                                             
     65         'fields': 'effective_object_story_id',                                                                                                                                             
                                                                                                                                                                                                   
ipdb> url                                                                                                                                                                                          
'https://graph.facebook.com/v19.0/6570769429896'                                                                                                                                                   
ipdb> n                                                                                                                                                                                            
> /Users/tuyentd/personal/huuthinh/autopost/utils/ad_post_utils.py(69)get_ad_effective_object_story_id()                                                                                           
     68                                                                                                                                                                                            
---> 69     response = requests.get(url, params=params)                                                                                                                                            
     70                                                                                                                                                                                            
                                                                                                                                                                                                   
ipdb> n                                                                                                                                                                                            
> /Users/tuyentd/personal/huuthinh/autopost/utils/ad_post_utils.py(71)get_ad_effective_object_story_id()                                                                                           
     70                                                                                                                                                                                            
---> 71     if response.status_code == 200:                                                                                                                                                        
     72         data = response.json()                                                                                                                                                             
                                                                                                                                                                                                   
ipdb> response.text                                                                                                                                                                                
'{"effective_object_story_id":"471948829668444_871576291649212","id":"6570769429896"}'                                                                                                             
ipdb> exit                                                                                                                                                                                         
Traceback (most recent call last):                                                        