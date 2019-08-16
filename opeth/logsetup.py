'''Logging setup - file and console logs. 

Logger is available through ``logging.getLogger("logger")``.
'''

import datetime
import logging
import os

def in_ipython():
    try:
        __IPYTHON__
    except NameError:
        return False
    else:
        return True
    
if in_ipython():
    # ipython does not work properly with colorama yet
    has_colorama = False
    print("Ipython running, colorama missing -> error messages are not highlighted")
else:
    try:
        import colorama
        has_colorama = True
        colorama.init()
    except Exception as e:
        print("Colorama missing, error messages are not highlighted")
        has_colorama = False 

class LogFormatter(logging.Formatter):
    def format(self, record):
        if record.levelno >= logging.ERROR:
            self._fmt = record.levelname + ": %(message)s"
        else:
            self._fmt = "%(message)s"

        return super(LogFormatter, self).format(record)

class FileLogFormatter(logging.Formatter):
    def format(self, record):
        if record.levelno > logging.INFO:
            self._fmt = record.levelname + ": %(message)s"
        else:
            self._fmt = "%(message)s"
        ts = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S:   ')
        self._fmt = ts + self._fmt

        return super(FileLogFormatter, self).format(record)

class LogHandler(logging.StreamHandler):
    def handle(self, record):
        if has_colorama and record.levelno >= logging.ERROR:
            print(colorama.Fore.WHITE + colorama.Back.RED + colorama.Style.BRIGHT)
        elif has_colorama and record.levelno >= logging.WARNING:
            print(colorama.Fore.YELLOW)
        super(LogHandler, self).handle(record)
        if has_colorama and record.levelno >= logging.WARNING:
            print(colorama.Style.RESET_ALL)

def init_logs(logfile=None, loglevel=logging.DEBUG, **kwargs):
    logger = logging.getLogger("logger")
    # global log level should be the minimum of all handlers
    logger.setLevel(loglevel) 

    lh = LogHandler()
    formatter = LogFormatter()
    lh.setFormatter(formatter)
    logger.addHandler(lh)
    
    if logfile is not None:
        lh2 = logging.FileHandler(logfile, 'at+')
        fileformatter = FileLogFormatter()
        lh2.setFormatter(fileformatter)
        lh2.setLevel(logging.INFO) 
        logger.addHandler(lh2)

    logger.info("Level %s set for logging." % logging.getLevelName(logger.getEffectiveLevel()))
    
    return logging.getLogger("logger") 
