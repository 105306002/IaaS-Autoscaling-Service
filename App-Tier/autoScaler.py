import boto3
from queue import Queue
import time
import base64
import socket
from datetime import datetime
import signal
import math
import sys
from enum import Enum
import PyInstaller.__main__
from subprocess import Popen, PIPE
from http.server import HTTPServer, SimpleHTTPRequestHandler
import socketserver
import threading

# Define the maximum number of instances allowed
MAX_INSTANCES = 20

# Initialize the queue to track instance IDs
instance_ids_queue = []

sqs = boto3.client('sqs', region_name='us-east-1')
ec2 = boto3.client('ec2', region_name='us-east-1')
iam = boto3.client('iam')

IAM_ROLE_NAME= "CSE546-Project1CreateAWSServicesFromEC2Instance"
IAMEC2RoleARN = ""

#sudo -u ubuntu pip3 install --user boto3 torch
#sudo -u ubuntu echo  REPLACE_WITH_BASE_64 | base64 -d > /home/ubuntu/appTierTransfer.tar.gz
#sudo -u ubuntu python3 /home/ubuntu/appTier.py
# Autoscaler elastic IP address ec2-34-230-241-211.compute-1.amazonaws.com:8080
EC2FirstRunCommands = """#!/bin/bash
time sudo -u ubuntu wget http://ec2-34-230-241-211.compute-1.amazonaws.com:8080/dist/appTier -O /home/ubuntu/appTier
sudo -u ubuntu chmod +x /home/ubuntu/appTier
sudo -u ubuntu /home/ubuntu/appTier
"""

AppTierReplacePattern = "REPLACE_WITH_BASE_64"

EC2SecurityGroupName = 'CSE546-Project1SecurityGroup' 

AppTierWebServerPort = 8080

lastMessageCount = 0

class AppTierInstanceStatus(Enum):
    WorkingOnTask = 1,
    NotWorkingOnTask = 2,
    StartingInstance = 3


def compileApptierScript():
    PyInstaller.__main__.run([
        'appTier.py',
        '--onefile',
    ])


server = HTTPServer(("", AppTierWebServerPort), SimpleHTTPRequestHandler)
thread = threading.Thread(target = server.serve_forever)
thread.daemon = True
thread.start()

def getApptierInstanceStatus(ipAddrStr):
    client_socket = socket.socket()  # instantiate
    client_socket.settimeout(2)
    try:
        client_socket.connect((ipAddrStr, 1337)) 

        
        data = client_socket.recv(1024).decode()
        client_socket.close()
    except:
        print("  Connecting to server timed out, returning StartingInstance")
        return AppTierInstanceStatus.StartingInstance # Waiting for EC2 instance to start up
    
    if data == "True":
        return AppTierInstanceStatus.WorkingOnTask
    else:
        return AppTierInstanceStatus.NotWorkingOnTask
    
    
def ensureIAMRole():

    response = iam.get_instance_profile(
        InstanceProfileName = IAM_ROLE_NAME
    )
    global IAMEC2RoleARN
    IAMEC2RoleARN = response['InstanceProfile']['Arn']


def get_security_group_id():
    for rds_security_group in ec2.describe_security_groups()['SecurityGroups']:
        if rds_security_group['GroupName'] == EC2SecurityGroupName:
            return (rds_security_group['GroupId']) # Found ID for name
    return False


def create_instance(instance_name):
    security_group_id = get_security_group_id()

    if security_group_id == False:
        vpc_id = ec2.describe_vpcs().get('Vpcs', [{}])[0].get('VpcId', '')
        
        response = ec2.create_security_group(
            GroupName = EC2SecurityGroupName,
            Description = 'DESCRIPTION',
            VpcId = vpc_id
        )
        security_group_id = response['GroupId']
        print('Security Group Created %s in vpc %s.' % (security_group_id, vpc_id))

        securityGroupIngress = ec2.authorize_security_group_ingress(
            GroupId=security_group_id,
            IpPermissions=[
                {
                    'IpProtocol': 'tcp',
                    'FromPort': 22,
                    'ToPort': 22,
                    'IpRanges': [{'CidrIp': '0.0.0.0/0'}]
                },
                {
                    'IpProtocol': 'tcp',
                    'FromPort': 1337,
                    'ToPort': 1337,
                    'IpRanges': [{'CidrIp': '0.0.0.0/0'}]
                }
            ]
        )

    # Replace temporary pattern with base64 encoded appTier.py script
    with open("./appTier.py", "rb") as appTierFile:
        b64EncodedScript = base64.b64encode(appTierFile.read())

        global EC2FirstRunCommands
        EC2FirstRunCommands = EC2FirstRunCommands.replace(AppTierReplacePattern, b64EncodedScript.decode("utf-8"))

    # Define the parameters for launching the instance
    instance_params = {
        'ImageId': 'ami-09c6ef0459a2ff40e', # The AMI ID of the instance
        'InstanceType': 't2.micro',  # The instance type (e.g., 't2.micro')
        'KeyName': 'project1SharedKey',    # The name of your EC2 key pair
        'MinCount': 1,              # Minimum number of instances to launch
        'MaxCount': 1,              # Maximum number of instances to launch
        'TagSpecifications': [
            {
                'ResourceType': 'instance',
                'Tags': [
                    {'Key': 'Name', 'Value': instance_name},
                ]
            }
        ],
        "IamInstanceProfile": {
            "Arn": IAMEC2RoleARN
        },
        "UserData" : EC2FirstRunCommands,

        "NetworkInterfaces": [
            {
                "AssociatePublicIpAddress": True,
                "DeviceIndex": 0,
                "Groups": [
                    security_group_id
                ]
            }
        ],
    }

    # Launch the instance
    response = ec2.run_instances(**instance_params)

    # Get the instance ID of the newly created instance
    instance_id = response['Instances'][0]['InstanceId']
    instance_ipAddress = response['Instances'][0]['PrivateIpAddress']

    print(f"Instance {instance_name} (ID: {instance_id}, IP: {instance_ipAddress}) has been created.")

    return instance_id, instance_ipAddress


def terminate_instance(instance_id):
    # Terminate the instance
    ec2.terminate_instances(InstanceIds=[instance_id])

    print(f"  Instance with ID {instance_id} has been terminated.")


def check_and_scale(queue_url, resp_queue_url, autoscale_threshold_up, minimium_ec2_instances):
    global lastMessageCount

    request = sqs.get_queue_attributes(
        QueueUrl=queue_url,
        AttributeNames=['ApproximateNumberOfMessages']
    )
    message_count = int(request['Attributes']['ApproximateNumberOfMessages'])

    op_response = sqs.get_queue_attributes(
        QueueUrl=resp_queue_url,
        AttributeNames=['ApproximateNumberOfMessages']
    )
    op_message_count = int(op_response['Attributes']['ApproximateNumberOfMessages'])


    # Calculate the number of instances currently running
    global instance_ids_queue
    running_instances = len(instance_ids_queue)
    print("Input SQS messages: ", message_count, "Running instances: ", running_instances, "Output SQS messages: ", op_message_count)
    if message_count > running_instances or (running_instances < minimium_ec2_instances):
        print("SQS message count exceeds EC2 availability: ", message_count, " > ", running_instances)
        instances_to_create = int(math.floor(message_count - running_instances + 1) / 2) #running_instances - message_count + 1     #(message_count // autoscale_threshold_up) + 1


        if running_instances == 0: # If no instances are started start minimium
            instances_to_create = minimium_ec2_instances # 0 index ranged for

        # Ensure that the total number of instances doesn't exceed the maximum
        if instances_to_create + running_instances > 20:
            instances_to_create = 20 - running_instances

        for i in range(instances_to_create):
            instance_name= f'app-instance{len(instance_ids_queue) + 1}'
            instance_id, instance_intIpAddr  = create_instance(instance_name)
            instance_ids_queue.append({
                "id": instance_id,
                "creationTime" : datetime.now(),
                "num" : len(instance_ids_queue) + 1,
                "internalIpAddress": instance_intIpAddr,
                "toBeRemoved": False,
            })

    running_instances = len(instance_ids_queue)
    if running_instances > (message_count * 0.75) and running_instances > minimium_ec2_instances and not (message_count ^ lastMessageCount): # XNOR the message counts to prevent read errors where one read just returns a 0 but the others are correct

        for i in range(len(instance_ids_queue)):
            inst = instance_ids_queue[i]

            print('Check DS: ID: ', inst['id'], "Sec:", (datetime.now() - inst['creationTime']).total_seconds(), "num: ", inst['num'])
            if (datetime.now() - inst['creationTime']).total_seconds() > 30 and inst['num'] > 2: # Don't delete the first two #2.5 * 2
                isInUse = getApptierInstanceStatus(inst["internalIpAddress"])
                print("  In use: ", isInUse)
                if isInUse == AppTierInstanceStatus.NotWorkingOnTask or (isInUse == AppTierInstanceStatus.StartingInstance and message_count < 2):
                    terminate_instance(inst['id'])

                    originalIndex = next((index for (index, d) in enumerate(instance_ids_queue) if d["id"] == inst["id"]), None)
                    instance_ids_queue[originalIndex]['toBeRemoved'] = True # Set deleted flag
        
        # Removed deleted instances from queue
        instance_ids_queue = [d for d in instance_ids_queue if d['toBeRemoved'] != True]

    lastMessageCount = message_count


def handleSIGINT(sig, frame):
    signal.signal(sig, signal.SIG_IGN)
    print("Caught SIGINT- Terminating instances")
    for i in instance_ids_queue:
        terminate_instance(i['id'])

    server.shutdown()
    sys.exit(0)


if __name__ == "__main__":
    AUTOSCALE_THRESHOLD_UP = 20  # Threshold for scaling up
    AUTOSCALE_THRESHOLD_DOWN = 2  # Threshold for scaling down
    QUEUE_URL = 'https://sqs.us-east-1.amazonaws.com/580774365972/CSE546-Project1SendToAppTierQueue'
    RESPONSE_QUEUE_URL = 'https://sqs.us-east-1.amazonaws.com/580774365972/CSE546-Project1SendToWebTierQueue'

    signal.signal(signal.SIGINT, handleSIGINT)

    compileApptierScript()

    ensureIAMRole()

    # Run the scaling logic periodically
    while True:
        check_and_scale(QUEUE_URL,RESPONSE_QUEUE_URL, AUTOSCALE_THRESHOLD_UP, AUTOSCALE_THRESHOLD_DOWN)
        time.sleep(1)
