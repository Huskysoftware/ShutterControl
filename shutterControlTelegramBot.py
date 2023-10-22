import telepot
import telepot.loop
import time
import datetime
import threading
import shutterControl
import gettext
import astral
import urllib3
import os
import configparser
from typing import Union


_ = gettext.gettext


INI_FILENAME: str = os.path.expanduser('~/.shutterControl.ini')
INI_KEY_TELEGRAM_BOT_TOKEN: str = 'Telegram bot token'
INI_KEY_ALLOWED_TELEGRAM_USERS: str = 'Allowed Telegram usernames'

UPDATE_EVERY_SECONDS: int = 10
BOT_CONTACT_RETRY_DELAY_SECONDS: int = 5

CMDS_OFF = ('off', 'aus')
CMDS_UP = ('up', 'rauf', 'auf', 'hoch', 'open')
CMDS_DOWN = ('down', 'runter', 'zu', 'close', 'shut')
CMDS_DAWN = ('dawn', 'dämmerung ein', 'dämmerung')
CMDS_NODAWN = ('nodawn', 'dämmerung aus')
CMDS_DEPRESSION_CIVIL = (
	'depression civil',
	'depression zivil',
	'civil',
	'zivil')
CMDS_DEPRESSION_NAUT = (
	'depression nautical',
	'depression nautisch',
	'nautical',
	'nautisch')
CMDS_DEPRESSION_ASTRO = (
	'depression astronomical',
	'depression astronomisch',
	'astronomical',
	'astronomisch')
CMDS_LATEST = {'latest', 'max', 'spätestens'}
CMDS_STATUS = ('status', 'settings', 'einstellungen')
CMDS_HELP = ('help', 'hilfe')

# The following commands represent only the leading part of the command
# which must be followed by a floating point number
CMDS_DEPRESSION_FLOAT_ARG = ('depression', )


HELP_TXT: str = _(
	'Available commands:\n\n'
	'*`<hh:mm>`*: Set wake up time\n'
	'*`off    `*: Do not wake up at any time\n'
	'*`dawn   `*: Close shutters at dawn\n'
	'*`nodawn `*: Don\'t close shutters at dawn\n'
	'\n'
	'*`up     `*: Open shutters now\n'
	'*`down   `*: Close shutters now\n'
	'\n'
	'*`depression [civil|nautical|astronomical]:`*\n'
	'*`depression <degrees below horizon>:`*\n'
	'    Set depression for dawn time calculation\n'
	'\n'
	'*`latest <hh:mm[:ss]>:`*\n'
	'    Close at that time, even if before dawn\n'
	'\n'
	'*`status `*: Print settings and next event\n'
	'*`help   `*: Print this help text\n'
)


bot: telepot.Bot = None
allowed_chat_id: int = -1
allowed_telegram_usernames: tuple[str] = ()
next_event: shutterControl.Event = shutterControl.Event(False, None)


def update_next_event():
	global next_event

	settings = shutterControl.read_settings_from_db()
	next_event = shutterControl.determine_next_event(settings)


def modify_settings(
	dawn_close: Union[None, bool] = None,
	open_at:    Union[None, str]  = None,
	depression: Union[None, float, astral.Depression] = None,
	latest:     Union[None, str] = None
) -> None:
	shutterControl.write_settings_to_db(
		dawn_close, open_at, depression, latest)
	update_next_event()


def status_msg():
	settings = shutterControl.read_settings_from_db()
	close_at_dawn = settings.close_at_dawn
	open_at_time = settings.open_at_time
	depression = settings.depression
	latest = settings.latest
	msg = (
		_('Settings:\n`Close at dawn = {}\n').format(
			_('ON') if close_at_dawn else _('OFF'))
	)
	if close_at_dawn == True:
		if latest != None:
			msg += _('Latest at: {}\n').format(latest.isoformat())
		msg += _('Depression = {}\n').format(depression)
	msg += (
		_('Wakeup time = {}`\n\n').format(
			open_at_time.isoformat() if open_at_time != None else _('OFF'))
	)
	if next_event != None:
		msg += (
			_('Next event:\n`{} ').format(
				_('OPEN') if next_event.open else _('CLOSE')) +
			_('at {}`').format(
				next_event.time.isoformat(sep=' ', timespec='seconds'))
		)
	else:
		msg += _('No next event scheduled')
	return msg


def send_status_msg():
	if allowed_chat_id >= 0:
		bot.sendMessage(allowed_chat_id, status_msg(), parse_mode='MarkdownV2')


def send_help_text():
	if allowed_chat_id >= 0:
		bot.sendMessage(allowed_chat_id, HELP_TXT, parse_mode='MarkdownV2')


def is_isoformat_time(time_str):
	try:
		datetime.time.fromisoformat(time_str)
		return True
	except:
		return False


def telegram_message_handler(msg):
	global allowed_telegram_usernames

	message = msg['text'].lower().strip() if 'text' in msg else ''
	split_msg = message.split()
	print(f'Msg received: {msg}')

	if ('username' in msg['from']
				and msg['from']['username'] in allowed_telegram_usernames):
		# Save chat ID; will be used for sending subsequent messages
		global allowed_chat_id
		allowed_chat_id = msg['chat']['id']

		if is_isoformat_time(message):
			modify_settings(open_at=message)
			send_status_msg()

		# Process <h:mm> just like <hh:mm> time format, e.g. '8:32' as '08:32'
		elif is_isoformat_time('0' + message):
			modify_settings(open_at='0' + message)
			send_status_msg()

		elif message in CMDS_OFF:
			modify_settings(open_at='off')
			send_status_msg()

		elif message in CMDS_DAWN:
			modify_settings(dawn_close=True)
			send_status_msg()

		elif message in CMDS_NODAWN:
			modify_settings(dawn_close=False)
			send_status_msg()

		elif message in CMDS_UP:
			shutterControl.actuate_shutters(True)
			bot.sendMessage(allowed_chat_id, _('OK, opening shutters...'))

		elif message in CMDS_DOWN:
			shutterControl.actuate_shutters(False)
			bot.sendMessage(allowed_chat_id, _('OK, closing shutters...'))

		elif message in CMDS_DEPRESSION_CIVIL:
			modify_settings(depression=astral.Depression.CIVIL)
			send_status_msg()
			
		elif message in CMDS_DEPRESSION_NAUT:
			modify_settings(depression=astral.Depression.NAUTICAL)
			send_status_msg()
			
		elif message in CMDS_DEPRESSION_ASTRO:
			modify_settings(depression=astral.Depression.ASTRONOMICAL)
			send_status_msg()

		elif split_msg[0] in CMDS_DEPRESSION_FLOAT_ARG:
			try:
				modify_settings(depression=float(split_msg[1]))
				send_status_msg()
			except:
				bot.sendMessage(allowed_chat_id, _('Wrong argument format'))
				send_help_text()

		elif split_msg[0] in CMDS_LATEST:
			try:
				if split_msg[1] in CMDS_OFF:
					modify_settings(latest='off')
					send_status_msg()
				elif is_isoformat_time(split_msg[1]):
					modify_settings(latest=split_msg[1])
					send_status_msg()
				elif is_isoformat_time('0' + split_msg[1]):
					modify_settings(latest='0'+split_msg[1])
					send_status_msg()
				else:
					bot.sendMessage(allowed_chat_id, _('Unknown command'))
					send_help_text()
			except:
				bot.sendMessage(allowed_chat_id, _('Wrong argument format'))
				send_help_text()

		elif message in CMDS_STATUS:
			send_status_msg()

		elif message in CMDS_HELP:
			send_help_text()

		else:
			bot.sendMessage(allowed_chat_id, _('Unknown command'))
			send_help_text()

	else:
		# This is a message from a not allowed user; react accordingly
		bot.sendMessage(allowed_chat_id, _('Contact trial from:'))
		bot.sendMessage(allowed_chat_id, repr(msg))


def shutter_control_loop():
	global next_event, allowed_chat_id
	while True:
		if next_event != None and next_event.time != None:
			now = datetime.datetime.now(datetime.timezone.utc)
			if now >= next_event.time:
				current_event_open: bool = next_event.open
				shutterControl.actuate_shutters(current_event_open)
				update_next_event()
				if allowed_chat_id >= 0:
					try:
						if current_event_open:
							bot.sendMessage(allowed_chat_id,
								_('Opening shutters...'))
						else:
							bot.sendMessage(allowed_chat_id,
								_('Closing shutters...'))
						send_status_msg()
					except:
						# If Telegram msg cannot be sent: Continue loop anyway
						pass
		time.sleep(UPDATE_EVERY_SECONDS)


def main():
	global bot
	global allowed_telegram_usernames

	# Read configuration from .ini file
	config = configparser.ConfigParser()
	num_files_successfully_read = len(config.read(INI_FILENAME))
	if num_files_successfully_read == 0:
		raise FileNotFoundError(INI_FILENAME)
	bot_token = (
		config[configparser.DEFAULTSECT][INI_KEY_TELEGRAM_BOT_TOKEN]
		.strip())
	allowed_telegram_usernames = (
		config[configparser.DEFAULTSECT][INI_KEY_ALLOWED_TELEGRAM_USERS]
		.strip().split('\n'))

	# Initialize Telegram bot
	bot = telepot.Bot(bot_token)
	while True:
		try:
			print(f'{bot.getMe()=}')
			# If above command was successful: exit loop
			break
		except urllib3.exceptions.MaxRetryError:
			# If bot.getMe() was not successful, wait a bit, then try again
			print('Error in bot.getMe(); trying again in '
				f'{BOT_CONTACT_RETRY_DELAY_SECONDS} seconds...')
			time.sleep(BOT_CONTACT_RETRY_DELAY_SECONDS)


	# Initialize GPIO pins
	shutterControl.init_gpio()

	# Read settings from database and determine next event
	update_next_event()

	# Start shutterControlLoop thread
	shutter_control_loop_thread = threading.Thread(target=shutter_control_loop)
	shutter_control_loop_thread.start()

	# Enter endless Telegram message processing loop
	telepot.loop.MessageLoop(bot, telegram_message_handler).run_forever()


if __name__ == '__main__':
	main()
