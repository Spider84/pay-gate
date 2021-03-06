#!/usr/bin/env python
"""#"""
# -*- coding: utf-8 -*-

import sys
import os
import logging
import imaplib
import email
import threading
import time
import re
import io
import gettext
import traceback
import html
import json
import random
import tempfile
import socket
import shutil
from datetime import datetime
from email.header import decode_header
from telegram import Update, ParseMode
from telegram.ext import Updater, CommandHandler, MessageHandler, Filters, CallbackContext
from PIL import Image, ImageDraw, ImageFont
from pay_gate.charset import sevenSegLarge
if sys.platform != 'win32':
    from OPi import GPIO
    from oled.device import ssd1306, sh1106 # pylint: disable=unused-import

PIN_NUM = 26                                             # номер ноги на разъёме для реле
INVERT_PIN = False                                       # инвертировать логику ноги
LED_NUM = 0                                              # не используется пока
TOKEN = ''                                               # токен бота
CHANNEL_ID = 0                                           #куда слать широковещания
SAVER_TIME = (60, 5)                                     #время статичной картинки, время чёрного экрана в секндах
QR_NUM = 0                                               #номер QR для сравнения в EMAIL
QR_CODE = ''                                             # ссылка внутри QR кода
PAY_COEF = 0.8
NOTIFY_INTERVAL = 60
ADMINS = []                                              # список админов бота
SUDO_KEY = '321456'                                      # пароль для всех не админов
APPEND_TIME = 0                                          # время добавляемое к основному
RE_SCRIPT = '^[\\w\\s]+\\:\\s*(\\d+)\\.\\s*[\\w\\s]+\\:\\s*(\\d+\\.\\d{2})\\s*RUB\\.\\s*QR\\s*:\\s*(\\d+)\\.\\r?$'
#'^Код подтверждения\\:\\s*(\\d+)\\.\\s*Сумма\\:\\s*(\\d+\\.\\d{2})\\s*RUB\\.\\s*QR\\s*:\\s*(\\d+)\\.\\r?$'
#'^TEXT\\s*\\:.*\\s(\\d+)\\..*\\:\\s*(\\d+\\.\\d{2})\\s*RUB\\.\\s*QR\\s*:\\s*(\\d+)\\.\r?$'

IMAP_SERVER = ''
EMAIL_LOGIN = ''
EMAIL_PASSWORD = ''
EMAIL_INTERVAL = 10

SCREENS_DIR = 'screens'
LIB_DIR = '/var/lib/pay_gate' if sys.platform != 'win32' else 'lib' #папка  данными
LOG_PATH = os.path.join(LIB_DIR, 'log')                  #папка с логами
LOGO_FILE = 'logo.png'                                   #файл логотипа

gettext.translation('pay_gate', os.path.join(os.path.dirname(__file__), './translations'), fallback=True, languages=['ru', 'en']).install()

# Enable logging
logger = logging.getLogger()

mail_thread = 0
work_thread = 0
bot = 0
oled = 0
logo_img = Image.new('1', (128, 64))
serial = ''
work_start = float(0)
work_length = float(0)
FONT2 = None
static_image = 0
screen = Image.new('1', (128, 64))

def get_ip_address():
    """Получение текущего IP адреса для сообщения о нём хозяину"""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(10)
    s.connect(("8.8.8.8", 80))
    return s.getsockname()[0]

def generate_logo(logo_file):
    """Генерация QR кода в случае отсутвия изображения заставки"""
    import qrcode # pylint: disable=import-outside-toplevel

    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_L,
        box_size=2,
        border=0,
    )
    qr.add_data(QR_CODE)
    qr.make(fit=True)

    qr_img = qr.make_image(fill_color="white", back_color="black")
    qr_img.convert("L")

    del qr

    logo_img.paste(qr_img, (int((screen.width/2)-(qr_img.width/2)), 0))

    del qr_img

    logo_img.convert("L")
    logo_img.save(logo_file, "PNG")
    logger.info("QR Generated")

def turnRelayOn():
    """Включение реле."""
    logger.info('Relay On')
    try:
        GPIO.output(PIN_NUM, GPIO.HIGH if INVERT_PIN else GPIO.LOW)
    except Exception:
        pass

def turnRelayOff():
    """Выключение реле."""
    logger.info('Relay Off')
    try:
        GPIO.output(PIN_NUM, GPIO.LOW if INVERT_PIN else GPIO.HIGH)
    except Exception:
        pass

def saveWork(starter):
    """Сохранение состояния работы."""
    data = {
        'starter': starter,
        'start': int(work_start),
        'length': int(work_length)
    }
    with open(os.path.join(LIB_DIR, 'work.json'), 'w') as outfile:
        json.dump(data, outfile)

def loadWork():
    """Загрузка последнего сохраненого состояния работы"""
    try:
        with open(os.path.join(LIB_DIR, 'work.json')) as json_file:
            data = json.load(json_file)
            now = datetime.timestamp(datetime.now())
            if data['start'] > 0 and data['length'] > 0 and (now - int(data['start'])) < int(data['length']):
                global work_start, work_length, bot
                work_start = data['start']
                work_length = data['length']
                turnRelayOn()
                bot.send_message(chat_id=CHANNEL_ID, text=_("Restoring prev work!"), parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
    except Exception:
        pass

def checkIsAdmin(from_user):
    """Проверка на вхождение в список админов"""
    if len(ADMINS)<=0:
        return True
    return (from_user.id in ADMINS) or ((from_user.username is not None) and (from_user.username in ADMINS))

def user_name(from_user):
    """Форматирование имени отправителя комнады в читанемый вид"""
    name = from_user.username if from_user.username is not None else from_user.name
    return name if name is not None else from_user.id

# Define a few command handlers. These usually take the two arguments update and
# context. Error handlers also receive the raised TelegramError object in error.
def start(update, _context):
    """Send a message when the command /start is issued."""
    update.message.reply_text(_('Send /help cmd for all commands list'))

def help_command(update, _context):
    """Send a message when the command /help is issued."""
    update.message.reply_text(_('My commands list is:\n\t/serial - my serial number\n\t/state - current gate state\n\t/turnon {minutes} - open gate for {minutes} time\n\t/turnoff - close gate immediately\n\t/logs {cmd} [params] - work with log files, where {cmd} is:\n\t\tlist [page] - list log files from {page}, where {page} is page number by 10 files\n\t\tget {file_name} - downlaod log file {filename}\n\t\tclear {file_name} - clear log {filename}\n\t/savers {cmd} [params] - work with screen savers files, where {cmd} is:\n\t\tadd - add new image file\t\tlist [page] - list files from {page}, where {page} is page number by 10 files\n\t\tget {file_name} - downlaod image file {filename}\n\t\tdel {file_name} - delete image file {filename}\n/logo {cmd} [params] - work with logo, where {cmd} is:\n\t\tadd - replace current logo with uploaded\n\t\tget - downlaod logo image file\n\t\tdel - delete logo image file and replace by QR code\n'))

def bot_screen(update, _context):
    """Обработчик команды бота screen."""
    if (update.message is None):
        return
    imgByteArr = io.BytesIO()
    screen.save(imgByteArr, format='PNG')
    imgByteArr.seek(0, 0)
    update.message.reply_photo(imgByteArr)

def bot_state(update, _context):
    """Обработчик команды бота state."""
    if (update.message is None):
        return
    text = ""
    logger.info('State requested by %s', user_name(update.message.from_user))
    if work_start != 0:
        now = datetime.timestamp(datetime.now())
        text = _('Elapsed time: {} of {}').format(int(now - work_start), int(work_length))
    else:
        text = _('On Idle')
    update.message.reply_text(text)

def bot_turnon(update, context):
    """Обработчик команды бота turnoff."""
    if (update.message is None) or (not checkIsAdmin(update.message.from_user)):
        return
    logger.info('Turn on requested by %s', user_name(update.message.from_user))
    if len(context.args) == 1 and context.args[0].isdigit():
        global work_start, work_length, oled
        if work_start == 0 or work_length == 0:
            work_length = int(context.args[0])*60
            work_start = datetime.timestamp(datetime.now())
            logger.info('Starting work for %d sec', int(work_length))
            turnRelayOn()
            update.message.reply_text(_('Starting work').format(int(work_length/60)))
            saveWork(user_name(update.message.from_user))
        else:
            update.message.reply_text(_('I\'m already in work!'))
    else:
        update.message.reply_text(_('What you want?'))

def bot_password(update, context):
    """Обработчик команды бота password."""
    if (update.message is None):
        return
    if len(context.args) == 1 and type(context.args[0]) == str:
        global ADMINS
        if not (update.message.from_user.id in ADMINS) and not (update.message.from_user.username in ADMINS):
            ADMINS.append(update.message.from_user.id)

def document_handler(update, context):
    """Обработчик события загрузки файла."""
    if 'saver_upload' in context.chat_data:
        old_job = context.chat_data['saver_upload']
        old_job.schedule_removal()
        del context.chat_data['saver_upload']
        new_file_name = os.path.join(SCREENS_DIR, update.message.document.file_name)
        if os.path.isfile(new_file_name):
            update.message.reply_text(_('Sorry, but this file already exists'))
        else:
            file = context.bot.getFile(update.message.document)
            file.download(custom_path=new_file_name)
            try:
                im = Image.open(new_file_name)
                if im.width != 128 or im.height != 64 or im.mode not in set(['1', 'L', 'P']):
                    im.close()
                    del im
                    update.message.reply_text(_('Sorry, but picture must be 128x64 mono color'))
                    os.remove(new_file_name)
                else:
                    im.close()
                    del im
                    update.message.reply_text(_('Thx for new screen saver'))
            except Exception:
                update.message.reply_text(_('Sorry, but file must be a picture'))
                os.remove(new_file_name)
    elif 'logo_upload' in context.chat_data:
        old_job = context.chat_data['logo_upload']
        old_job.schedule_removal()
        del context.chat_data['logo_upload']

        new_file_name = os.path.join('/tmp', LOGO_FILE)

        file = context.bot.getFile(update.message.document)
        file.download(custom_path=new_file_name)
        try:
            im = Image.open(new_file_name)
            if im.width != 128 or im.height != 64 or im.mode not in set(['1', 'L', 'P']):
                im.close()
                del im
                update.message.reply_text(_('Sorry, but picture must be 128x64 mono color'))
                os.remove(new_file_name)
            else:
                im.close()
                del im

                update.message.reply_text(_('Thx for new logo'))

                try:
                    global work_start, logo_img, oled, screen
                    logo_file_name = os.path.join(LIB_DIR, LOGO_FILE)
                    if os.path.isfile(logo_file_name):
                        os.remove(logo_file_name)
                    shutil.move(new_file_name, logo_file_name)
                    logo_img = Image.open(logo_file_name)

                    if work_start == 0:
                        draw = ImageDraw.Draw(screen)
                        draw.rectangle([(0, 0), screen.size], fill=0)
                        screen.paste(logo_img, (0, 0))
                        try:
                            oled.display(screen)
                        except Exception:
                            pass
                except Exception as e:
                    logger.error("Logo upload error: %s", e)
        except Exception:
            update.message.reply_text(_('Sorry, but file must be a picture'))
            os.remove(new_file_name)

def saver_upload_timeout(_update, context):
    """Обработчик таймаута на загрузку изображения."""
    job = context.job
    context.bot.send_message(job.context, text='Sorry, but you late....')

def bot_logo(update, context):
    """Обработчик команды бота logo."""
    if (update.message is None) or (not checkIsAdmin(update.message.from_user)):
        return
    logger.info('Logo requested by %s', user_name(update.message.from_user))
    if len(context.args) >= 1:
        cmd = context.args[0].lower()
        if cmd == 'add':
            if 'saver_upload' in context.chat_data:
                old_job = context.chat_data['saver_upload']
                old_job.schedule_removal()
                del context.chat_data['saver_upload']
                update.message.reply_text(_('Oh! I already waiting for screen saver. Ok, changing task...'))

            if 'logo_upload' in context.chat_data:
                old_job = context.chat_data['logo_upload']
                old_job.schedule_removal()
                update.message.reply_text(_('Oh! I already waiting for file. Ok. Will wait for new...'))
            else:
                update.message.reply_text(_('Ok. I\'m waiting for new file...'))
            chat_id = update.message.chat_id
            new_job = context.job_queue.run_once(saver_upload_timeout, 60, context=chat_id)
            context.chat_data['logo_upload'] = new_job
        elif cmd == 'get':
            file_name = os.path.join(LIB_DIR, LOGO_FILE)
            if os.path.isfile(file_name):
                try:
                    with open(file_name, 'rb') as f:
                        update.message.reply_document(f)
                except Exception:
                    pass
            else:
                update.message.reply_text(_('Sorry, but this file is not exists'))
        elif cmd == 'del':
            file_name = os.path.join(LIB_DIR, LOGO_FILE)
            if os.path.isfile(file_name):
                global logo_img, screen, oled
                os.remove(file_name)
                logo_img = Image.new('1', (128, 64))
                generate_logo(file_name)
                if work_start == 0:
                    draw = ImageDraw.Draw(screen)
                    draw.rectangle([(0, 0), screen.size], fill=0)
                    screen.paste(logo_img, (0, 0))
                    try:
                        oled.display(screen)
                    except Exception:
                        pass
                update.message.reply_text(_('Custom logo removed'))
            else:
                update.message.reply_text(_('Sorry, but this file is not exists'))

def bot_savers(update, context):
    """Обработчик команды бота savers."""
    if (update.message is None) or (not checkIsAdmin(update.message.from_user)):
        return
    logger.info('Savers requested by %s', user_name(update.message.from_user))
    if len(context.args) >= 1:
        cmd = context.args[0].lower()
        if cmd == 'add':
            if 'logo_upload' in context.chat_data:
                old_job = context.chat_data['logo_upload']
                old_job.schedule_removal()
                del context.chat_data['logo_upload']
                update.message.reply_text(_('Oh! I already waiting for new logo. Ok, changing task...'))

            if 'saver_upload' in context.chat_data:
                old_job = context.chat_data['saver_upload']
                old_job.schedule_removal()
                update.message.reply_text(_('Oh! I already waiting for file. Ok. Will wait for new...'))
            else:
                update.message.reply_text(_('Ok. I\'m waiting for new file...'))
            chat_id = update.message.chat_id
            new_job = context.job_queue.run_once(saver_upload_timeout, 60, context=chat_id)
            context.chat_data['saver_upload'] = new_job
        elif cmd == 'del':
            if len(context.args) >= 2:
                file_name = os.path.join(SCREENS_DIR, context.args[1])
                if os.path.isfile(file_name):
                    try:
                        os.remove(file_name)
                        update.message.reply_text(_('Screen image file {} is deleted').format(context.args[1]))
                    except Exception:
                        pass
                else:
                    update.message.reply_text(_('Sorry, but this file is not exists'))
        elif cmd == 'get':
            if len(context.args) >= 2:
                file_name = os.path.join(SCREENS_DIR, context.args[1])
                if os.path.isfile(file_name):
                    try:
                        with open(file_name, 'rb') as f:
                            update.message.reply_document(f)
                    except Exception:
                        pass
                else:
                    update.message.reply_text(_('Sorry, but this file is not exists'))

def bot_logs(update, context):
    """Обработчик команды бота logs."""
    if (update.message is None) or (not checkIsAdmin(update.message.from_user)):
        return
    logger.info('Logs requested by %s', user_name(update.message.from_user))
    if len(context.args) >= 1:
        cmd = context.args[0].lower()
        if cmd == 'list':
            log_files = ''
            cnt = 0
            page = 0
            if len(context.args) >= 2 and context.args[1].isdigit():
                page = int(context.args[1])
            if os.path.isdir(LOG_PATH):
                for f in os.listdir(LOG_PATH):
                    if os.path.isfile(os.path.join(LOG_PATH, f)):
                        if cnt >= page*10:
                            log_files += f + '\n'
                        cnt += 1
                        if cnt+(page*10) >= 10:
                            log_files += _('({})...').format(page+1)
                            break
                if cnt <= 0:
                    log_files += _('no more files')
            else:
                log_files += _('no logs directory')
            update.message.reply_text(log_files)
            return
        elif cmd == 'get':
            if len(context.args) >= 2:
                file_name = os.path.join(LOG_PATH, context.args[1])
                if os.path.isfile(file_name):
                    try:
                        doc = open(file_name, 'rb')
                        update.message.reply_document(doc)
                        doc.close()
                    except Exception as _e:
                        update.message.reply_text(_('Error: Unable to send file'))
                else:
                    update.message.reply_text(_('Error: No such file'))
            return
        elif cmd == 'clear':
            if len(context.args) >= 2:
                file_name = os.path.join(LOG_PATH, context.args[1])
                if os.path.isfile(file_name):
                    try:
                        os.unlink(file_name)
                        update.message.reply_text(_('Deleted.'))
                    except Exception as _e:
                        update.message.reply_text(_('Error: Unable to delete file'))
                else:
                    update.message.reply_text(_('Error: No such file'))
            return
    update.message.reply_text(_('What you want?'))

def bot_serial(update, _context):
    """Обработчик команды бота serial."""
    if (update.message is None) or (not checkIsAdmin(update.message.from_user)):
        return
    logger.info('Serial requested by %s', user_name(update.message.from_user))
    update.message.reply_text(serial)

def bot_turnoff(update, _context):
    """Обработчик команды бота turnoff."""
    if (update.message is None) or (not checkIsAdmin(update.message.from_user)):
        return
    global work_start, work_length, oled, screen
    logger.info('Turn off requested by %s', user_name(update.message.from_user))
    if work_start != 0:
        work_length = 0
        work_start = 0
        logger.info('Work stopped')
        update.message.reply_text(_('Work stopped!'))
        turnRelayOff()
        draw = ImageDraw.Draw(screen)
        draw.rectangle([(0, 0), screen.size], fill=0)
        screen.paste(logo_img, (0, 0))
        try:
            oled.display(screen)
        except Exception:
            pass
        saveWork(user_name(update.message.from_user))
    else:
        update.message.reply_text(_('I\'m already do nothing...'))

def check_work():
    """Основаня рабочая петля. Реализует конечный автомат состояний."""
    global oled, static_image
    last_notify = 0

    t = threading.currentThread()
    e = getattr(t, "e")
    while not getattr(t, "stop", False):
        global work_start, work_length, logo_img, FONT2
        now = datetime.timestamp(datetime.now())
        if work_start > 0 and work_length > 0:
            elapsed_time = now - work_start
            if work_length <= elapsed_time:
                logger.info('Work end by time')
                turnRelayOff()

                draw = ImageDraw.Draw(screen)
                draw.rectangle([(0, 0), screen.size], fill=0)
                draw.text((0, 0), _("Pay time: {:02d}:{:02d}").format(int(work_length/60), int(work_length%60)), font=FONT2, fill=255)
                draw.text((0, 25), _("Time is elapsed"), font=FONT2, fill=255)
                try:
                    oled.display(screen)
                except Exception:
                    pass

                time.sleep(5)
                draw.rectangle([(0, 0), screen.size], fill=0)
                screen.paste(logo_img, (0, 0))
                try:
                    oled.display(screen)
                except Exception:
                    pass

                work_length = 0
                work_start = 0
                last_notify = 0

                bot.send_message(chat_id=CHANNEL_ID, text=_("Stop work!"), parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
                saveWork(None)

                static_image = now
            else:
                draw = ImageDraw.Draw(screen)
                draw.rectangle([(0, 0), screen.size], fill=0)
                draw.text((0, 0), _("Pay time: {:02d}:{:02d}").format(int(work_length/60), int(work_length%60)), font=FONT2, fill=255)
                drawTime(screen, int(work_length-elapsed_time), 0, 16, sevenSegLarge)
                drawProgress(screen, int(elapsed_time), int(work_length))
                try:
                    oled.display(screen)
                except Exception:
                    pass

                if NOTIFY_INTERVAL>0:
                    if last_notify <= 0:
                        last_notify = work_start
                    if now-last_notify >= NOTIFY_INTERVAL:
                        elapsed = (work_length-elapsed_time)
                        last_notify = now
                        logger.info('Elapsed notification %d', int(elapsed))
                        elapsed = int(elapsed/60)
                        bot.send_message(chat_id=CHANNEL_ID, text=_('Elapsed time {} min').format(int(elapsed)), parse_mode=ParseMode.MARKDOWN, disable_web_page_preview=True)
        else:
            if static_image == 0:
                static_image = now
            if static_image >= 0 and now-static_image >= SAVER_TIME[0]:
                draw = ImageDraw.Draw(screen)
                try:
                    file = random.choice(os.listdir(SCREENS_DIR))
                    im = Image.open(os.path.join(SCREENS_DIR, file))
                    im.convert("L")
                    screen.paste(im, (0, 0))
                    im.close()
                    del im
                except Exception as _e:
                    draw.rectangle([(0, 0), screen.size], fill=0)
                try:
                    oled.display(screen)
                except Exception:
                    pass
                static_image = 0 - now
            elif static_image < 0 and now - (0 - static_image) >= SAVER_TIME[1]:
                static_image = now
                draw = ImageDraw.Draw(screen)
                draw.rectangle([(0, 0), screen.size], fill=0)
                screen.paste(logo_img, (0, 0))
                try:
                    oled.display(screen)
                except Exception:
                    pass
        e.wait(timeout=1)
    logger.info("Work stopped")

def check_mail():
    """Поток проверки почты на сервере."""
    t = threading.currentThread()
    e = getattr(t, "e")
    while not getattr(t, "stop", False):
        try:
            mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        except Exception as er:
            logger.error("Connect to IMAP server: %s", er)
            e.wait(timeout=60)
            continue
        try:
            mail.login(EMAIL_LOGIN, EMAIL_PASSWORD)
        except Exception as er:
            logger.error("Mail auth error: %s", er)
            e.wait(timeout=60)
            continue
        mail.select("inbox")

        result, data = mail.uid('search', None, "NOT SEEN")
        if result.lower() == "ok":
            uids = data[0].split()
            if len(uids) > 0:
                latest_email_uid = uids[-1]
                result, data = mail.uid('fetch', latest_email_uid, '(RFC822)')
                if result.lower() == "ok":
                    message = email.message_from_bytes(data[0][1])

                    mail_from, _from_encode = decode_header(message['from'])[0]
                    mail_subject, _encoding = decode_header(message['subject'])[0]
                    charset = message.get_param('charset', 'ascii')

                    try:
                        logger.info('EMAIL from %s with Subject: %s', mail_from.decode(_from_encode), mail_subject.decode(_encoding))
                    except (UnicodeDecodeError, AttributeError):
                        pass

                    if message.is_multipart():
                        mail_content = ''

                        # on multipart we have the text message and
                        # another things like annex, and html version
                        # of the message, in that case we loop through
                        # the email payload
                        for part in message.get_payload():
                            # if the content type is text/plain
                            # we extract it
                            if part.get_content_type() == 'text/plain':
                                mail_content += part.get_payload(None, True).decode(charset)
                    else:
                        # if the message isn't multipart, just extract it
                        mail_content = message.get_payload(None, True).decode(charset)

                    # and then let's show its result
                    # print(f'From: {mail_from}')
                    # print(f'Subject: {mail_subject}')
                    # print(f'Content: {mail_content}')

                    mail.uid("STORE", latest_email_uid, '+FLAGS', '\\Seen \\Deleted')

                    global bot, work_start, work_length, QR_NUM
                    if work_start == 0:
                        global RE_SCRIPT
                        m = re.search(RE_SCRIPT, mail_content, re.MULTILINE | re.UNICODE)
                        if m is not None:
                            pay = float(m.groups()[1])
                            _qr_num = int(m.groups()[2])

                            if _qr_num == QR_NUM and pay > 0:
                                logger.info('Payment detected %.2f', pay)
                                bot.send_message(CHANNEL_ID, _('Payment detected {}!').format(pay), "Markdown", True)
                                work_start = datetime.timestamp(datetime.now())
                                work_length = int((60 * pay)*PAY_COEF) + APPEND_TIME
                                turnRelayOn()
                                saveWork(m.groups()[0])

        mail.close()
        mail.logout()
        e.wait(timeout=EMAIL_INTERVAL)
    logger.info("Mail check stopped")

def drawProgress(display, seconds, totalSeconds):
    """Отрисовка прогресс бара."""
    if display.height < 64:
        y = 31
    else:
        y = 56
    draw = ImageDraw.Draw(display)
    for py in range(y - 3, y + 4):
        draw.point((10, py), fill=255)
        draw.point((117, py), fill=255)
    if seconds > 0 and totalSeconds > 0:
        progress = float(float(seconds) / float(totalSeconds) * 107.0)
        for x in range(107):
            if x <= progress:
                draw.point((x + 10, y - 1), fill=255)
                draw.point((x + 10, y), fill=255)
                draw.point((x + 10, y + 1), fill=255)
            else:
                draw.point((x + 10, y - 1), fill=0)
                draw.point((x + 10, y), fill=0)
                draw.point((x + 10, y + 1), fill=0)


def _drawChar(display, char, x, y, cw, cbh, chset):
    draw = ImageDraw.Draw(display)
    for sx in range(0, cw):
        for sy in range(0, cbh):
            dy = y
            chdata = chset[char][sx + sy * cw]
            for bit in [0, 1, 2, 3, 4, 5, 6, 7]:
                draw.point(((sx + x), ((8 * sy) + dy)), fill=(255 if ((chdata >> bit) & 0x01) != 0 else 0))
                dy += 1


def drawTime(display, seconds, x, y, charset, fullsize=True, center=True):
    """Отрисовка времени."""
    hours = seconds // 3600
    seconds %= 3600
    minutes = seconds // 60
    seconds = seconds % 60

    cw = charset[11][0]
    ch = charset[11][1]
    digit_stride = charset[11][2]
    colon_stride = charset[11][3]

    if fullsize and center:
        w = (digit_stride * 4) + colon_stride + colon_stride + cw
        x = (128 - w) / 2

    elif not fullsize and center:
        w = (digit_stride * 3) + colon_stride + cw
        x = (128 - w) / 2

    pos = x
    if fullsize:
        _drawChar(display, hours, pos, y, cw, ch, charset)  # hours
        pos += digit_stride
        _drawChar(display, 10, pos, y, cw, ch, charset)  # :
        pos += colon_stride
    _drawChar(display, minutes // 10, pos, y, cw, ch, charset)  # min 10
    pos += digit_stride
    _drawChar(display, minutes % 10, pos, y, cw, ch, charset)  # min 1
    pos += digit_stride
    _drawChar(display, 10, pos, y, cw, ch, charset)  # :
    pos += colon_stride
    _drawChar(display, seconds // 10, pos, y, cw, ch, charset)  # sec 10
    pos += digit_stride
    _drawChar(display, seconds % 10, pos, y, cw, ch, charset)  # sec 1

def getSerial():
    """Получение серийого номера платы."""
    _serial = 'UNK'
    pattern = r"^Serial\s+\:\s*(\S+)$"
    if sys.platform == 'win32':
        file1 = open('cpuinfo', 'r')
    else:
        file1 = open('/proc/cpuinfo', 'r')
    for line in file1:
        line = line.strip()
        m = re.search(pattern, line)
        if m is not None:
            _serial = str(m.groups()[0])
            break
    file1.close()
    return _serial

def error_handler(update: Update, context: CallbackContext):
    """Log the error and send a telegram message to notify the developer."""
    # Log the error before we do anything else, so we can see it even if something breaks.
    logger.error(msg="Exception while handling an update:", exc_info=context.error)

    # traceback.format_exception returns the usual python message about an exception, but as a
    # list of strings rather than a single string, so we have to join them together.
    tb_list = traceback.format_exception(None, context.error, context.error.__traceback__)
    tb = ''.join(tb_list)

    # Build the message with some markup and additional information about what happened.
    # You might need to add some logic to deal with messages longer than the 4096 character limit.
    message = (
        'An exception was raised while handling an update\n'
        'Version: {}\n'
        '<pre>update = {}</pre>\n\n'
        '<pre>context.chat_data = {}</pre>\n\n'
        '<pre>context.user_data = {}</pre>\n\n'
        '<pre>{}</pre>'
    ).format(
        '1.0.8',
        html.escape(json.dumps(update.to_dict(), indent=2, ensure_ascii=False)),
        html.escape(str(context.chat_data)),
        html.escape(str(context.user_data)),
        html.escape(tb)
    )

    try:
        # Finally, send the message
        context.bot.send_message(chat_id=191835312, text=message, parse_mode=ParseMode.HTML)
    except Exception:
        pass

def loadSettings():
    """Загрузка настроек бота из файла"""
    config_json = '/etc/pay-gate.json'
    if os.path.isfile(config_json):
        with open(config_json) as json_file:
            config = json.load(json_file)

            if 'hw' in config is not None:
                global PIN_NUM, LED_NUM, INVERT_PIN
                if 'relay_pin' in config['hw'] and type(config['hw']['relay_pin']) == int:
                    PIN_NUM = int(config['hw']['relay_pin'])
                if 'invert_relay' in config['hw'] and type(config['hw']['invert_relay']) in [int, bool]:
                    INVERT_PIN = int(config['hw']['invert_relay'])!=0
                if 'led_pin' in config['hw'] and type(config['hw']['led_pin']) == int:
                    LED_NUM = int(config['hw']['led_pin'])

            try:
                global PAY_COEF
                PAY_COEF = float(config['pay']['coeficient'])
            except Exception:
                logger.warning("Missing Pay Coeficient, using default %.2f", PAY_COEF)

            if 'bonus' in config['pay'] and type(config['pay']['bonus']) in [int]:
                global APPEND_TIME
                APPEND_TIME = int(config['pay']['bonus'])

            try:
                global NOTIFY_INTERVAL
                NOTIFY_INTERVAL = int(config['telegram']['notify_interval'])
            except Exception:
                logger.warning("Missing NOTIFY_INTERVAL, using default %u", NOTIFY_INTERVAL)

            try:
                global TOKEN, CHANNEL_ID, QR_NUM, QR_CODE, SAVER_TIME, IMAP_SERVER, EMAIL_LOGIN, EMAIL_PASSWORD, EMAIL_INTERVAL, ADMINS, RE_SCRIPT
                TOKEN = config['telegram']['token']
                CHANNEL_ID = config['telegram']['channel_id']

                if 'admins' in config['telegram'] and type(config['telegram']['admins']) in [list, tuple]:
                    ADMINS = []
                    for adm_id in config['telegram']['admins']:
                        ADMINS.append(adm_id)

                if 'password' in config['telegram'] and type(config['telegram']['password']) == str:
                    SUDO_KEY = config['telegram']['password']

                QR_NUM = config['QR']['num']
                QR_CODE = config['QR']['url'].format(QR_NUM)
                if 'script' in config['email'] and type(config['email']['script']) == str:
                    re_script = config['email']['script']
                    try:
                        re.compile(re_script)
                        RE_SCRIPT = re_script
                    except re.error:
                        logger.warning("Wrong REGEXP script for E-MAIL '%s'", re_script)

                SAVER_TIME = (int(config['saver']['delay']), int(config['saver']['show']))
                IMAP_SERVER = config['email']['server']
                EMAIL_LOGIN = config['email']['login']
                EMAIL_PASSWORD = config['email']['password']
                EMAIL_INTERVAL = int(config['email']['interval'])
            except Exception as e:
                logger.error("Missing config value: %s", e)
                sys.exit()
            else:
                return
    sys.exit()

def sig_handler(signum, _frame):
    """Обработчик системных сигналов"""
    global oled, screen, FONT2, mail_thread, work_thread
    logger.info("Received %s signal.", signum)

    bot.send_message(CHANNEL_ID, _('Bot shutdown request...'), "Markdown", True)

    if mail_thread.is_alive():
        mail_thread.stop = True
        mail_thread.e.set()
    if work_thread.is_alive():
        work_thread.stop = True
        work_thread.e.set()

    mail_thread.join()
    work_thread.join()

    draw = ImageDraw.Draw(screen)
    draw.rectangle([(0, 0), screen.size], fill=0)
    text = _("System\nShutdown")
    text_width, text_height = draw.multiline_textsize(text, font=FONT2)
    draw.multiline_text((((screen.width-text_width)/2), ((screen.height-text_height)/2)), text, font=FONT2, fill=255, align="center")
    try:
        oled.display(screen)
    except Exception:
        pass

def main():
    """Start the bot."""
    global bot, oled, logo_img, FONT2, serial, SCREENS_DIR, mail_thread, work_thread, FONT2

    # Проверяем есть ли папка для сохранения данных
    if not os.path.isdir(LIB_DIR):
        os.mkdir(LIB_DIR)

    if not os.path.exists(LOG_PATH):
        os.mkdir(LOG_PATH)

    logFormatter = logging.Formatter("%(asctime)s [%(threadName)-12.12s] [%(levelname)-5.5s]  %(message)s")

    pkg_name = vars(sys.modules[__name__])['__package__']
    if pkg_name is None:
        pkg_name = __name__

    fileHandler = logging.FileHandler('{0}/{1}.log'.format(LOG_PATH, pkg_name))
    fileHandler.setFormatter(logFormatter)
    logger.addHandler(fileHandler)

    consoleHandler = logging.StreamHandler(sys.stdout)
    consoleHandler.setFormatter(logFormatter)
    logger.addHandler(consoleHandler)

    logger.setLevel(logging.INFO)

    logger.info("Service started")

    #Проверяем можно ли писать в эту папку
    try:
        fd, name = tempfile.mkstemp(dir=LIB_DIR)
    except Exception as _e:
        logger.error("Storage is not writable")
    else:
        os.close(fd)
        os.remove(os.path.join(LIB_DIR, name))

    SCREENS_DIR = os.path.join(LIB_DIR, SCREENS_DIR)
    if not os.path.isdir(SCREENS_DIR):
        os.mkdir(SCREENS_DIR)

    loadSettings()

    try:
        model = None
        board_json = '/etc/board.json'
        if os.path.isfile(board_json):
            with open(board_json) as json_file:
                board = json.load(json_file)
                if board['model'] is not None and board['model']['id'] is not None:
                    _manuf, model = board['model']['id'].split(',', 2)

        GPIO.setwarnings(False)

        if model == 'orangepi-zero':
            import orangepi.zero # pylint: disable=unused-import, import-outside-toplevel
            GPIO.setmode(orangepi.zero.BOARD)
        else:
            import orangepi.zeroplus2 # pylint: disable=unused-import, import-outside-toplevel
            GPIO.setmode(orangepi.zeroplus2.BOARD)

        GPIO.setup(PIN_NUM, GPIO.OUT)
        GPIO.output(PIN_NUM, GPIO.LOW if INVERT_PIN else GPIO.HIGH)

        oled = ssd1306(port=0, address=0x3C)
    except Exception as e:
        logger.error("Unable to init Hardware %s", e)

    try:
        FONT2 = ImageFont.truetype(os.path.join(os.path.dirname(__file__), 'fonts/C&C Red Alert [INET].ttf'), 15)
    except Exception as e:
        logger.error("Unable to Load font: %s", e)

    logo_loaded = False
    logo_file = os.path.join(LIB_DIR, LOGO_FILE)
    if os.path.isfile(logo_file):
        logo_img = Image.open(logo_file)
        logo_img.convert("L")
        logger.info("QR Loaded")
        logo_loaded = True
    if not logo_loaded:
        generate_logo(logo_file)

    ImageDraw.Draw(screen).rectangle([(0, 0), screen.size], fill=0)
    screen.paste(logo_img, (0, 0))

    try:
        oled.display(screen)
    except Exception:
        pass

    serial = getSerial()
    logger.info('My serial is : %s', serial)

    # Create the Updater and pass it your bot's token.
    # Make sure to set use_context=True to use the new context based callbacks
    # Post version 12 this will no longer be necessary
    updater = Updater(TOKEN, use_context=True, user_sig_handler=sig_handler)

    # Get the dispatcher to register handlers
    dp = updater.dispatcher

    # on different commands - answer in Telegram
    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("help", help_command))

    dp.add_handler(CommandHandler("state", bot_state))
    dp.add_handler(CommandHandler("turnon", bot_turnon))
    dp.add_handler(CommandHandler("turnoff", bot_turnoff))
    dp.add_handler(CommandHandler("logs", bot_logs, pass_args=True))
    dp.add_handler(CommandHandler("serial", bot_serial))
    dp.add_handler(CommandHandler("screen", bot_screen))
    dp.add_handler(CommandHandler("savers", bot_savers, pass_args=True, pass_job_queue=True, pass_chat_data=True))
    dp.add_handler(CommandHandler("logo", bot_logo, pass_args=True, pass_job_queue=True, pass_chat_data=True))
    dp.add_handler(CommandHandler("password", bot_password))
    dp.add_handler(MessageHandler(Filters.document, document_handler))

    # ...and the error handler
    dp.add_error_handler(error_handler)

    logger.info("Bot started")

    # Start the Bot
    updater.start_polling()

    bot = updater.bot

    mail_thread = threading.Thread(target=check_mail, name="check_mail")
    mail_thread.e = threading.Event()
    work_thread = threading.Thread(target=check_work, name="check_work")
    work_thread.e = threading.Event()

    loadWork()

    mail_thread.start()
    work_thread.start()

    while True:
        try:
            bot.send_message(CHANNEL_ID, _('Bot Started'), "Markdown", True)
        except Exception:
            time.sleep(10)
            continue
        else:
            break

    bot.send_message(CHANNEL_ID, _('My IP: {}').format(get_ip_address()), "Markdown", True)

    # Run the bot until you press Ctrl-C or the process receives SIGINT,
    # SIGTERM or SIGABRT. This should be used most of the time, since
    # start_polling() is non-blocking and will stop the bot gracefully.
    updater.idle()

    GPIO.cleanup()

if __name__ == '__main__':
    main()
