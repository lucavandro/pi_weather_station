import os
class Config:
    # Weather Underground
    STATION_ID = ""
    STATION_KEY = ""
    PICTURE_RESOLUTION = "1280x720"
    PRESERVE_OLD_PICTURES = True
    MEASUREMENT_INTERVAL = 1  # In minuti
    DATA_UPLOAD_INTERVAL = 5  # In minuti
    PICTURE_UPLOAD_INTERVAL = 5 # In minuti
    ICON_UPDATE_INTERVAL = 10 # In minuti
    WELCOME_MESSAGE = "Stazione metereologica"
    WEATHER_UPLOAD = True
    WEBCAM_ENABLED = True
    FTP_SERVER = "webcam.wunderground.com"
    FTP_LOGIN = "WU_9120162CAM1"
    FTP_PASSWORD = ""
    API_KEY = ""
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

