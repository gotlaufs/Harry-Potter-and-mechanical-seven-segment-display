#!/usr/bin/env python3
""" Main Parrot app """

import time
import logging
import subprocess
import traceback

import picamera
import tinydb

import arduino_handler
import twitter_handler

# Messages will require moderation before they are displayed
# Only moderated messages will be displayed if 'True'
MODERATION_ON = True

# This should work on Raspberry, but just in case adjust as neccessary
ARDUINO_PORT = "/dev/ttyUSB0"

# Pause between main loop iterations
LOOP_DELAY = 15

# If True, will print the whole Python traceback on every handled exception
PRINT_FULL_EXCEPTION = False

# Should not me changed
VIDEO_FILE = "video.h264"
VIDEO_FILE2 = "video.mp4"
DB_FILE = "db.json"
# Use ffmpeg to put raw h.264 video in mp4 container with no re-encodeing
# 'y' to all questions
ENCODE_CMD = ["ffmpeg", "-y", "-i", VIDEO_FILE, "-c", "copy", VIDEO_FILE2]


def main():
    logging.info("Starting script")

    logging.info("Initializing Arduino communication")
    arduino = arduino_handler.ArduinoHandler(ARDUINO_PORT)
    logging.info("Setting Arduino display parameters")
    arduino.blank(False)
    arduino.letter_delay(100)
    arduino.word_delay(200)

    logging.info("Initializing camera")
    camera = picamera.PiCamera()
    camera.resolution = (1280, 720)

    logging.info("Initializing database")
    db = tinydb.TinyDB(DB_FILE)

    logging.info("Initializing Twitter")
    tw = twitter_handler.TwitterHandler()

    logging.info("Entering main loop.. Wait %d s" % LOOP_DELAY)

    while(True):
        # Sleep for some time to not swarm Twitter API
        # TODO: Change to countdown (function)
        time.sleep(LOOP_DELAY)
        # Attempt to get new tweets
        try:
            statuses = tw.get_messages_clean()
        except Exception as exc:
            if PRINT_FULL_EXCEPTION:
                print(traceback.format_exc())
            print(exc)

            logging.error("Exception while getting tweets! API rate limiting?")
            continue

        logging.info("Succesfully got %d tweets from API" % len(statuses))

        # Check against existing in database
        entry = tinydb.Query()
        for s in statuses:
            results = db.search(entry.ID == s["ID"])
            if len(results) == 0:
                logging.info("Got a new tweet with ID=<%s>" % s["ID"])
                # Add some fields for DB
                s["source"] = "Twitter"
                s["already_shown"] = False
                s["moderation"] = "None"
                s["too_long"] = False

                # Add new result to DB
                db.insert(s)
            elif len(results) == 1:
                logging.debug("Tweet with ID=<%s> already found in DB"
                              % s["ID"])
            elif len(results) > 1:
                logging.error("More than 1 tweet in db with id <%s>" % s["ID"])

        # Do moderation
        if MODERATION_ON:
            need_moderation = db.search(entry.moderation == "None")
            # TODO: Add moderation function
        else:
            logging.info("Message moderation is turned off, skipping..")

        # Get a list of messages to display
        to_display = db.search((entry.already_shown == False) &
                               entry.too_long == False)
        logging.info("Found %d messages that need displaying"
                     % len(to_display))

        # Try to display tweets that need displaying
        for t in to_display:
            moderation_ok = t["moderation"] = "Pass"
            if MODERATION_ON and not moderation_ok:
                logging.warning("This tweet <%s> requires moderation! Skip.")
                continue

            logging.info("Displaying message: %s" % t["Text"])
            logging.info("Starting video recording")
            time_start = time.time()
            camera.start_recording(VIDEO_FILE, format="h264", quality=23)
            try:
                arduino.say(t["Text"])
            except Exception as exc:
                if PRINT_FULL_EXCEPTION:
                    print(traceback.format_exc())
                print(exc)

                logging.error("Fail in Arduino comm.")
                continue

            logging.debug("Stopping recording")
            camera.stop_recording()
            time_stop = time.time()

            time_video = time_stop - time_start
            logging.info("Recording length is %d seconds" % time_video)
            if time_video > 30:
                logging.error("Recording too long! Dicarding..")
                # TODO: Database add discard option
                db.update({"too_long": True}, entry.ID == t["ID"])
                continue

            # Put raw video into MP4 container
            logging.info("Calling ffmpeg..")
            # Capture output, so it doesn't clog the screen
            p = subprocess.run(ENCODE_CMD, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
            if p.returncode == 0:
                logging.info("Video conversion done")
            else:
                logging.error("ffmpeg failed with code: %d" % p.returncode)
                continue

            # Post the video to Twitter
            m = get_reply_message()
            try:
                tw.post_video_reply(message=m, uid=t["ID"],
                                    video_file=VIDEO_FILE2)
            except Exception as exc:
                if PRINT_FULL_EXCEPTION:
                    print(traceback.format_exc())
                print(exc)

                logging.error("Some error while posting Twitter video")
                continue

            logging.info("Succesfully posted video tweet")
            logging.info("Marking entry in DB")
            db.update({"already_shown": True}, entry.ID == t["ID"])

        logging.info("Done with all the messages, restarting loop. Wait %d s"
                     % LOOP_DELAY)

    arduino.close()


def get_reply_message():
    """Return a text message that is attached to the reply video"""
    # TODO: Make this something interesting
    return "You say and I reply :)"


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
