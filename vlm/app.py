from chalice import Chalice
from chalice import NotFoundError, BadRequestError, ForbiddenError
from chalice import IAMAuthorizer, Rate
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
        }
      ]
    }
  }
}


'''@app.route('/')
def index():
    envs = ["TW_ACCT", "TW_SID", "TW_TOK", "TW_PHONE", "ST_CLIENT_ID", "ST_CLIENT_SECRET"]
    environment = {}
    for env in envs:
        environment[env] = True if os.environ.get(env) else False
    return {'environment': environment}
'''

@app.route('/reservation', methods=['POST'])
def addReservation():
    data = app.current_request.json_body
    name = data['name']
    phone = data['phone']
    checkout = data['checkout']
    # XXX Add to lock 
    # Add to DB

@app.route('/cancel', methods=['POST'])
def delReservation():
    data = app.current_request.json_body
    phone = data['phone']
    # XXX Del from lock 
    # Del from DB


# XXX - change tables to be keyed off installedAppId and config as values
def updateSetting(k, v):
    attributes = {
        'val': v
    }
    settings.update_item(
        Key={'key': k},
        UpdateExpression="SET " + ", ".join([x+"=:"+x for x,y in attributes.items()]),
        ExpressionAttributeValues=dict([(":"+x,y) for x,y in attributes.items()])
    )

def getSetting(k):
    return settings.get_item(Key={'key': k}).get('Item').get('val')
    
def subscribe(appId, token, to):
    url = "https://api.smartthings.com/installedapps/" + appId + "/subscriptions"
    data = {
        "sourceType": "DEVICE", 
        "device": {
            "deviceId": to
        }
    }
    headers = {'Authorization': "Bearer " + token}
    r = requests.post(url, headers=headers, json=data)
    app.log.debug("Subscibe response: " + str(r.status_code))

def unsubscribeAll(appId, token):
    url = "https://api.smartthings.com/installedapps/" + appId + "/subscriptions"
    headers = {'Authorization': "Bearer " + token}
    r = requests.delete(url, headers=headers)
    app.log.debug("response: " + str(r.status_code))

def handleLifecycleConfiguration(cfg):
    if cfg['phase'] == 'INITIALIZE':
        return cfgInit
    if cfg['phase'] == 'PAGE':
        return cfgPage

def saveConfig(cfg):
    for k, v in cfg.items():
        value = v[0]
        if value['valueType'] == "DEVICE":
            value = value['deviceConfig']['deviceId']
        elif value['valueType'] == 'STRING':
            value = value['stringConfig']['value']
        updateSetting(k, value)

def subscribeDevices(appId, auth, cfg):
     for k, v in cfg.items():
        value = v[0]
        if value['valueType'] == "DEVICE":
            subscribe(appId, auth, value['deviceConfig']['deviceId'])

def handleLifecycleInstall(appInfo):
    app.log.debug('Installed app: ' + str(appInfo))
    auth = appInfo['authToken']
    refr = appInfo['refreshToken']
    updateSetting('refreshToken', refr)
    appId = appInfo['installedApp']['installedAppId']
    cfg = appInfo['installedApp']['config']
    saveConfig(cfg)
    subscribeDevices(appId, auth, cfg)
    return {"installData": {}}

def handleLifecycleUpdate(cfg):
    app.log.debug('Updated with config: ' + str(cfg))
    auth = appInfo['authToken']
    appId = appInfo['installedApp']['installedAppId']
    refr = appInfo['refreshToken']
    updateSetting('refreshToken', refr)
    cfg = appInfo['installedApp']['config']
    unsubscribeAll(appId, auth)
    saveConfig(cfg)
    subscribeDevices(appId, auth, cfg)
    return {"updateData": {}}

def handleLifecycleEvent(evts):
    for evt in evts:
        if evt['eventType'] == "DEVICE_EVENT":
            capability = evt['deviceEvent']['capability']
            val = evt['deviceEvent']['value']
            app.log.debug(capability + " = " + str(val))
    return {"eventData": {}}

def handleLifecycleUninstall(evt):
    # Unsubscribe all devices ?
    return {"uninstallData": {}}

# SmartThings auth tokens only last 5 minutes.  The refresh token lasts 30 days.  
# Need to refresh that token periodically.
# https://smartthings.developer.samsung.com/docs/auth-and-permissions.html#Using-the-refresh-token
def getNewTokens():
    client_id = os.environ.get("ST_CLIENT_ID")
    client_secret = os.environ.get("ST_CLIENT_SECRET")
    if not client_id or not client_secret:
        app.log.error("ST_CLIENT_ID and ST_CLIENT_SECRET environment variables NEED to be set in .chalice/config")
        return
    app.log.debug("Refreshing tokens...")
    refresh_token = getSetting('refreshToken')
    app.log.debug("Refresh token: " + refresh_token)
    url = 'https://auth-global.api.smartthings.com/oauth/token'
    data = {
        "grant_type": "refresh_token",
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token
    }
    r = requests.post(url, auth=(client_id, client_secret), data=data)
    app.log.debug("New token response(" + str(r.status_code) + "): " + r.text)
    tokens = r.json()
    updateSetting('refreshToken', tokens['refresh_token'])
    return tokens['access_token']

# https://community.smartthings.com/t/correct-z-wave-lock-api-command/171573/6
def getLockCodes():
    deviceid = getSetting("lock")
    urlf = 'https://api.smartthings.com/v1/devices/{deviceId}/components/{componentId}/capabilities/{capabilityId}/status'
    url = urlf.format(deviceId=deviceid, componentId="main", capabilityId="lockCodes")
    auth = getNewTokens()
    headers = {'Authorization': "Bearer " + auth}
    r = requests.get(url, headers=headers)
    app.log.debug("getLockCodes response(" + str(r.status_code) + "): " + r.text)

def setLockCode(deviceId, slot, code, name):
    urlf = 'https://api.smartthings.com/v1/devices/{deviceId}/commands'
    url = urlf.format(deviceId=deviceid)
    data = {
        "commands": [{
            "component": "main",
            "capability": "lockCodes",
            "command": "setCode",
            "arguments": [
                slot, code, name
            ]
        }]
    }
    auth = getNewTokens()
    headers = {'Authorization': "Bearer " + auth}
    r = requests.post(url, headers=headers, json=data)
    app.log.debug("setLockCode response(" + str(r.status_code) + "): " + r.text)

def delLockCode(deviceId, slot):
    urlf = 'https://api.smartthings.com/v1/devices/{deviceId}/commands'
    url = urlf.format(deviceId=deviceid)
    data = {
        "commands": [{
            "component": "main",
            "capability": "lockCodes",
            "command": "deleteCode",
            "arguments": [
                slot
            ]
        }]
    }
    auth = getNewTokens()
    headers = {'Authorization': "Bearer " + auth}
    r = requests.post(url, headers=headers, json=data)
    app.log.debug("delLockCode response(" + str(r.status_code) + "): " + r.text)

@app.schedule(Rate(14, unit=Rate.DAYS))
def every_two_weeks(event):
    # Refresh our refresh token
    getNewTokens()

'''@app.schedule(Rate(1, unit=Rate.HOURS))
def every_hour(event):
    #getLockCodes()
    pass
'''

@app.lambda_function(name='smartapp')
def smartapp(event, context):
    app.log.debug("Received event with data: " + str(event))
    response = {}
    if event['lifecycle'] == "CONFIGURATION":
        response = handleLifecycleConfiguration(event['configurationData'])
    elif event['lifecycle'] == "INSTALL":
        response = handleLifecycleInstall(event['installData'])
    elif event['lifecycle'] == "UPDATE":
        response = handleLifecycleUpdate(event['installData'])
    elif event['lifecycle'] == "EVENT":
        response = handleLifecycleEvent(event['eventData']['events'])
    elif event['lifecycle'] == "UNINSTALL":
        response = handleLifecycleUninstall(event)

    return response
