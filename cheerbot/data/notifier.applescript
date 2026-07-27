-- Cheerbot notifier applet.
-- Compiled into ~/Applications/Cheerbot.app so notifications are attributed to
-- Cheerbot instead of a generic script host. Reads a three-line payload
-- (title, body, sound name) written by the Python side just before launch.

on run
	set payloadFile to (POSIX path of (path to home folder)) & "Library/Application Support/Cheerbot/pending.txt"

	set theTitle to "Cheerbot"
	set theBody to "You're doing better than you think."
	set theSound to ""

	try
		set payload to (read POSIX file payloadFile as «class utf8»)
		set previousDelimiters to AppleScript's text item delimiters
		set AppleScript's text item delimiters to linefeed
		set parts to text items of payload
		set AppleScript's text item delimiters to previousDelimiters

		if (count of parts) ≥ 1 and item 1 of parts is not "" then
			set theTitle to item 1 of parts
		end if
		if (count of parts) ≥ 2 and item 2 of parts is not "" then
			set theBody to item 2 of parts
		end if
		if (count of parts) ≥ 3 then
			set theSound to item 3 of parts
		end if
	end try

	if theSound is "" then
		display notification theBody with title theTitle
	else
		display notification theBody with title theTitle sound name theSound
	end if
end run
