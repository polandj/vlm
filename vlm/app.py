from chalice import Chalice
from chalice import NotFoundError, BadRequestError, ForbiddenError
import boto3
import requests
import os
import time

dynamodb = boto3.resource('dynamodb')
settings = dynamodb.Table('vlm_settings')
reservations = dynamodb.Table('vlm_reservations')

app = Chalice(app_name='vlm')
app.debug = True

cfgInit = {
    "configurationData": {
        "initialize": {
        "name": "VLM: Vacation Lock Manager",
        "description": "VLM: Manages your smart lock codes so you dont have to",
        "id": "app",
        "permissions": [
            "r:devices:*",
            "x:devices:*",
            "i:deviceprofiles:*"
        ],
      "firstPageId": "1"
        }
    }
}

cfgPage = {
  "configurationData": {
    "page": {
      "pageId": "1",
      "nextPageId": None,
      "previousPageId": "",
      "complete": True,
      "name": "Select devices for this automation",
      "sections": [
        {
          "name": "Lock to manage",
          "settings": [
            {
              "id": "lock",
              "name": "Which lock?",
              "description": "Tap to set",
              "type": "DEVICE",
              "required": False,
              "multiple": False,
              "capabilities": [
                "lockCodes"
              ],
              "permissions": [
                "r:devices:*"
              ]
            }
          ]
        }, { 
            "name": "Door to monitor",
            "settings": [
                {
                    "id":"door",
                    "name": "Which door?",
                    "description": "Tap to set",
                    "type": "DEVICE",
                    "required": False,
                    "multiple": False,
                    "capabilities": [
                        "contactSensor"
                    ],
                    "permissions": [
                        "r:devices:*"
                    ]
                }
            ]
        }, {
          "name": "Twilio",
          "settings": [
           {
            "id": "twacct",
            "name": "Account",
            "description": "Tap to set",
            "type": "TEXT",
            "required": False,
            "defaultValue": "Account"
           },{
            "id": "twsid",
            "name": "SID",
            "description": "Tap to set",
            "type": "TEXT",
            "required": False,
            "defaultValue": "SID"
           },{
            "id": "twtok",
            "name": "Token",
            "description": "Tap to set",
            "type": "TEXT",
            "required": False,
            "defaultValue": "Token"
           },{
            "id": "twphone",
            "name": "Phone",
            "description": "Tap to set",
            "type": "TEXT",
            "required": False,
            "defaultValue": "Phone"
           }
          ]
        }
      ]
    }
  }
}

@app.route('/')
def index():
    return {'settings': settings.item_count, 'info': app.current_request.to_dict()}

def updateConfig(k, v):
    attributes = {
        'val': v
    }
    settings.update_item(
        Key={'key': k},
        UpdateExpression="SET " + ", ".join([x+"=:"+x for x,y in attributes.items()]),
        ExpressionAttributeValues=dict([(":"+x,y) for x,y in attributes.items()])
    )

def getConfig(k):
    return settings.get_item(Key={'key': k}).get('Item')
    
def subscribe(appId, to):
    url = "https://api.smartthings.com/installedapps/" + appId + "/subscriptions"
    data = {
        "sourceType": "DEVICE", 
        "device": {
            "deviceId": to
        }
    }
    r = requests.post(url, json=data)
    app.log.debug("Subscibe response: " + str(r.status_code))

def handleLifecycleConfiguration(cfg):
    if cfg['phase'] == 'INITIALIZE':
        return cfgInit
    if cfg['phase'] == 'PAGE':
        return cfgPage

def handleLifecycleInstall(appInfo):
    app.log.debug('Installed app: ' + str(appInfo))
    appId = appInfo['installedAppId']
    cfg = appInfo['config']
    # Save config
    for k, v in cfg.items():
        value = v[0]
        if value['valueType'] == "DEVICE":
            value = value['deviceConfig']['deviceId']
            subscribe(appId, value)
        elif value['valueType'] == 'STRING':
            value = value['stringConfig']['value']
        updateConfig(k, value)
    return {"installData": {}}

def handleLifecycleUpdate(cfg):
    app.log.debug('Updated with config: ' + str(cfg))
    # Save config
    for k, v in cfg.items():
        value = v[0]
        if value['valueType'] == "DEVICE":
            value = value['deviceConfig']['deviceId']
        elif value['valueType'] == 'STRING':
            value = value['stringConfig']['value']
        updateConfig(k, value)
    # Resubscribe to devices
    return {"updateData": {}}

def handleLifecycleEvent(evt):
    return {"eventData": {}}

def handleLifecycleUninstall(evt):
    # Unsubscribe all devices
    return {"uninstallData": {}}

@app.lambda_function(name='smartapp')
def smartapp(event, context):
    app.log.debug("Received event with data: " + str(event))
    response = {}
    if event['lifecycle'] == "CONFIGURATION":
        response = handleLifecycleConfiguration(event['configurationData'])
    elif event['lifecycle'] == "INSTALL":
        response = handleLifecycleInstall(event['installData']['installedApp'])
    elif event['lifecycle'] == "UPDATE":
        response = handleLifecycleUpdate(event['installData']['installedApp']['config'])
    elif event['lifecycle'] == "EVENT":
        response = handleLifecycleEvent(event)
    elif event['lifecycle'] == "UNINSTALL":
        response = handleLifecycleUninstall(event)

    return response
