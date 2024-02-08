import boto3
import socket
import threading
from subprocess import Popen, PIPE

sqs = boto3.client('sqs', region_name='us-east-1')
s3 = boto3.client('s3', region_name='us-east-1')

S3InputBucketName = "cse546-project1inputbucket"
S3OutputBucketName = "cse546-project1outputbucket"
newFileDownloadLocation = "/tmp/"

appTierReceiveQueue = "https://sqs.us-east-1.amazonaws.com/580774365972/CSE546-Project1SendToAppTierQueue" # The app tier pulls image urls/data from this queue
appTierSendQueue = "https://sqs.us-east-1.amazonaws.com/580774365972/CSE546-Project1SendToWebTierQueue" # The app tier pushes the results of the ML python script to this queue

atomicIsWorking = False

class notificationSocketServer(threading.Thread):
    def __init__(self, name):
        threading.Thread.__init__(self)
        self.name = name

    def run(self):
        global atomicIsWorking
        port = 1337
        server_socket = socket.socket()  
        server_socket.bind(("", port))
        print("Bound to all interfaces on port: ", port)

        # configure how many client the server can listen simultaneously
        server_socket.listen(2)
        
        while True:
            conn, address = server_socket.accept()  # accept new connection
            print("Connection from: " + str(address))
            conn.send(str(atomicIsWorking).encode())  # Send work status
            
            conn.close()

t = notificationSocketServer("notificationThread")
t.start()

while True:
    print("--- Waiting for new message")

    recQueueResponse = sqs.receive_message(QueueUrl=appTierReceiveQueue, MaxNumberOfMessages=1) 
    if 'Messages' in recQueueResponse: 

        atomicIsWorking = True

        msg = recQueueResponse['Messages'][0]["Body"]
        print("--- Received new message from Web tier/server: " + str(msg.encode('ascii', 'replace')))
        

        # Uncomment if message is the S3 file name
        print("Downloading image from input S3 bucket")
        fileName = msg
        imageData = s3.download_file(
            S3InputBucketName,                  # S3 Bucket name
            fileName,                           # S3 Bucket ID/file name
            newFileDownloadLocation + fileName  # Local file system save location
        )
        
        # Uncomment if message is the actual image data

        # Launch ML script
        print("Launching ML script")
        process = Popen(
            ["python3", "/home/ubuntu/app-tier/image_classification.py", newFileDownloadLocation + fileName], 
            stdout = PIPE,
            cwd = "/home/ubuntu/app-tier/"
        )
        (stdout, err) = process.communicate()

        # Write stdout of ML script into a file in the output S3 bucket
        print("Writing result to S3 output bucket")
        S3OutputStrippedFileName = msg.rsplit('.', 1)[0] # Takes cat.jpeg and transforms it into just 'cat'
        s3.put_object(
            Body = stdout.decode(),
            Bucket = S3OutputBucketName, 
            Key = S3OutputStrippedFileName
        )

        stdout = stdout.decode() or msg # Return msg if ML script has an issue and prematurely kills itself

        # Send result back through SQS
        print("Sending data back through SQS")
        sqs.send_message(
            QueueUrl = appTierSendQueue, 
            MessageBody = stdout
        ) 

        # Remove message from queue
        print("Removing original message from receive queue")
        sqs.delete_message(
            QueueUrl = appTierReceiveQueue,
            ReceiptHandle = recQueueResponse['Messages'][0]['ReceiptHandle']
        )

        # Remove mutex
        atomicIsWorking = False
