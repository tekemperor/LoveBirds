#credit to Louis Ros


#!/usr/bin/python3.5
import asyncio
import time
import os
import sys
import signal
from telethon import TelegramClient, events, sync
from telethon.tl.types import InputMessagesFilterVoice
import RPi.GPIO as GPIO
from gpiozero import Servo
from time import sleep


"""
initialisation of GPIOs
"""
global button_press_count   # number of button presses   since reset
global button_release_count # number of button releases  since reset
global heartBeatLed #heartbeat effect on led
global motorON     # motor command
global motorPin    # GPIO Pin for Motor
global p           # PWM for recLED  -- Used by HeartBeat
global playLED     #led you have a voicemail
global playNum     # Number of saved message to play
global playOK      # autorisation to play messages (boolean)
global previousMotorON #was the motor on before?
global recBUT      #button recording (mic+)
global recLED      #led recording (mic+)
global recording   # authorization to record a message (boolean)
global toPlay      # number of voicemail waiting

button_press_count = 0
button_release_count = 0
heartBeatLed = False
motorON = False
playNum = -1
playOK = True
previousMotorON = False
recording = False
toPlay = -1

motorPin = 17
playLED = 22
recBUT = 23
recLED = 25

"""
initialisation of GPIO leds and switch and motor
"""
GPIO.setmode(GPIO.BCM)
GPIO.setup(motorPin, GPIO.OUT)
GPIO.setup(playLED, GPIO.OUT)
GPIO.setup(recBUT, GPIO.IN)
GPIO.setup(recLED, GPIO.OUT)
GPIO.output(recLED, GPIO.LOW)

def button_callback(channel):
    global button_press_count
    global button_release_count
    if GPIO.input(recBUT) == GPIO.LOW:
        if button_press_count <= button_release_count:
            button_press_count += 1
    else:
        if button_release_count < button_press_count:
            button_release_count += 1

def button_reset():
    global button_press_count
    global button_release_count
    button_press_count = 0
    button_release_count = 0

async def control():
    """
    Determine actions based on user interaction
    """
    global button_press_count
    global button_release_count
    global heartBeatLed
    global p
    global playNum
    global playOK
    global recording

    while True:
        await asyncio.sleep(0.1)
        while button_press_count > 0:
            p.ChangeDutyCycle(100) #turns ON the REC LED
            press_count = button_press_count
            await asyncio.sleep(0.2)
            if press_count == button_press_count:
                p.ChangeDutyCycle(0)   #turns OFF the REC LED
            await asyncio.sleep(0.2)
            if (button_press_count == press_count and
                    button_release_count < button_press_count):
                await asyncio.sleep(0.4)
            if press_count == button_press_count:
                if button_release_count < button_press_count:
                    # Record Message
                    playOK = False
                    heartBeatLed = False
                    p.ChangeDutyCycle(100) #turns ON the REC LED
                    recording = True
                    while recording == True:
                        await asyncio.sleep(0.1)
                    playOK = True
                else:
                    # Play Message
                    heartBeatLed = False
                    p.ChangeDutyCycle(100) #turns ON the REC LED
                    playNum = button_release_count - 1
                    while playNum >= 0:
                        await asyncio.sleep(0.1)
                p.ChangeDutyCycle(0)   #turns OFF the REC LED
                button_reset()

async def recTG():
    """
    Send a message 'voice'
    initialisation of gpio led and button
    when button is pushed: recording in a separate process
    that is stopped when the button is released
    conversion to .oga by opusenc
    """
    global recording
    global button_press_count
    global button_release_count

    record_limit = 120  #seconds

    while True:
        await asyncio.sleep(0.1)
        if recording == True:
            pid = os.fork()
            if pid == 0 :
                os.execl('/usr/bin/arecord','arecord','--rate=44000','/home/pi/rec.wav','')
                os._exit(0)
            record_duration = 0.0
            while (button_press_count > button_release_count and
                    record_duration < record_limit):
                await asyncio.sleep(0.2)
                record_duration += 0.2
            os.kill(pid, signal.SIGHUP)
            recording = False
            if record_duration >= 0.5:
                os.system('/usr/bin/opusenc /home/pi/rec.wav /home/pi/rec.oga')
                await client.send_file(peer, '/home/pi/rec.oga', caption='LoveBirds Message', voice_note=True)

async def playTG():
    """
    when authorized to play (playOK == True)
    play one or several messages waiting (file .ogg) playLED on
    message playing => playing
    last message waiting => toPlay
    """
    global heartBeatLed
    global motorON
    global playNum
    global playOK
    global toPlay
    global p

    playing = 0
    for i in range(0,100):
        if os.path.exists('/home/pi/play' + str(i) + '.ogg'):
            playing = i
            break
    for i in range(playing,100):
        if not os.path.exists('/home/pi/play' + str(i) + '.ogg'):
            toPlay = i-1
            break

    while True:
        await asyncio.sleep(0.2)
        if playOK == False:
            continue

        if toPlay >= 0 and playNum < 0:
            GPIO.output(playLED, GPIO.HIGH)
            motorON = True
            heartBeatLed = True
        else:
            GPIO.output(playLED, GPIO.LOW)
            motorON = False
            heartBeatLed = False

        if toPlay >= 0 and playNum >= 0:
            while playing <= toPlay:
                name = '/home/pi/play' + str(playing) + '.ogg'
                os.system('sudo killall vlc')
                pid = os.fork()
                if pid == 0:
                    os.execl('/usr/bin/cvlc', 'cvlc', name,  '--play-and-exit')
                    os._exit(0)
                os.waitpid(pid, 0)
                await save_message(name)
                playing += 1
                if playing <= toPlay :
                    p.ChangeDutyCycle(0)
                    await asyncio.sleep(0.5)
                    p.ChangeDutyCycle(100)
                    await asyncio.sleep(0.5)
            playing = 0
            toPlay = -1
            playNum = -1
        elif playNum >= 0:
            name = '/home/pi/message' + str(playNum) + '.ogg'
            os.system('sudo killall vlc')
            pid = os.fork()
            if pid == 0:
                os.execl('/usr/bin/cvlc', 'cvlc', name,  '--play-and-exit')
                os._exit(0)
            os.waitpid(pid, 0)
            playNum = -1

async def save_message(new_message):
    for i in range(9, 0, -1):
        if os.path.exists('/home/pi/message' + str(i-1) + '.ogg'):
            os.replace('/home/pi/message' + str(i-1) + '.ogg', '/home/pi/message' + str(i) + '.ogg')
    os.replace(new_message, '/home/pi/message0.ogg')

#this is the les that mimic heartbeat when you have a voicemail waiting
async def heartBeat():
    global heartBeatLed
    global p

    p = GPIO.PWM(recLED, 500)          # set Frequece to 500Hz
    p.start(0)                         # Start PWM output, Duty Cycle = 0
    while True:
        if heartBeatLed == False:
            await asyncio.sleep(0.1)
            continue

        for dc in range(0, 20, 2):     # Increase duty cycle: 0~100
            await heartBeatDelta(dc)
            await asyncio.sleep(0.01)
        for dc in range(20, -1, -2):   # Decrease duty cycle: 100~0
            await heartBeatDelta(dc)
            await asyncio.sleep(0.005)
        await asyncio.sleep(0.05)
        for dc in range(0, 101, 2):    # Increase duty cycle: 0~100
            await heartBeatDelta(dc)
            await asyncio.sleep(0.01)
        for dc in range(100, -1, -2):  # Decrease duty cycle: 100~0
            await heartBeatDelta(dc)
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.06)
        for dc in range(0,8, 2):       # Increase duty cycle: 0~100
            await heartBeatDelta(dc)
            await asyncio.sleep(0.01)
        for dc in range(7, -1, -1):    # Decrease duty cycle: 100~0
            await heartBeatDelta(dc)
            await asyncio.sleep(0.01)
        await asyncio.sleep(1)

async def heartBeatDelta(duty_cycle):
    global heartBeatLed
    global p
    global button_press_count
    if heartBeatLed == True and button_press_count == 0:
        p.ChangeDutyCycle(duty_cycle)

#motor uses global to turn ON the motor
async def motor():
    global motorON
    global motorPin
    global previousMotorON
    # Adjust the pulse values to set rotation range
    min_pulse = 0.000544    # Library default = 1/1000
    max_pulse = 0.0024              # Library default = 2/1000
    # Initial servo position
    pos =  1
    test = 0
    servo = Servo(motorPin, pos, min_pulse, max_pulse, 20/1000, None)

    while True:
        await asyncio.sleep(0.2)
        if motorON == True:
            pos=pos*(-1)
            servo.value=pos
            await asyncio.sleep(2)
        else :
            #put back in original position
             servo.value=0
             #detach the motor to avoid glitches and save energy
             servo.detach()
             previousMotorON = False

"""
initialization of the application and user for telegram
init of the name of the correspondant with the file /boot/PEER.txt
declaration of the handler for the messages arrival
filtering of message coming from the correspondant
download of file .oga renamed .ogg

"""
GPIO.output(playLED, GPIO.HIGH)
motorON=True
api_id = 592944
api_hash = 'ae06a0f0c3846d9d4e4a7065bede9407'
client =  TelegramClient('session_name', api_id, api_hash)
asyncio.sleep(2)
client.connect()
if not  client.is_user_authorized():
    while os.path.exists('/home/pi/phone') == False:
        pass
    f = open('/home/pi/phone', 'r')
    phone = f.read()
    f.close()
    print(phone)

    asyncio.sleep(2)
    client.send_code_request(phone,force_sms=True)

    while os.path.exists('/home/pi/key') == False:
        pass
    f = open('/home/pi/key', 'r')
    key = f.read()
    f.close()
    print (key)
    os.remove('/home/pi/key')
    asyncio.sleep(2)
    me = client.sign_in(phone=phone, code=key)
GPIO.output(playLED, GPIO.LOW)
motorON=False

p = open('/boot/PEER.txt','r')
peer = p.readline()
if peer[-1] == '\n':
    peer = peer[0:-1]

@client.on(events.NewMessage)
async def receiveTG(event):
    global toPlay
    fromName = '@' + event.sender.username

    # only plays messages sent by your correpondant,
    # if you want to play messages from everybody
    # comment next line and uncomment the next next line
    if (event.media.document.mime_type  == 'audio/ogg') and (peer == fromName) :
    #if (event.media.document.mime_type == 'audio/ogg'):
        ad = await client.download_media(event.media)
        toPlay += 1
        if toPlay == 0:
            os.system('/usr/bin/cvlc --play-and-exit /home/pi/LB/lovebird.wav')
        name = '/home/pi/play' + str(toPlay) +  '.ogg'
        os.rename(ad,name)
        await asyncio.sleep(0.2)

"""
Main sequence (handler receiveTG), playTG, recTG, motor et heartBeat are excuted in parallel

"""
os.system('/usr/bin/cvlc --play-and-exit /home/pi/LB/lovebird.wav')
GPIO.add_event_detect(recBUT, GPIO.BOTH, callback=button_callback, bouncetime=10)

loop = asyncio.get_event_loop()
loop.create_task(control())
loop.create_task(recTG())
loop.create_task(playTG())
loop.create_task(motor())
loop.create_task(heartBeat())
loop.run_forever()
client.run_until_disconnected()

