all: localecompile

localecompile:
	django-admin compilemessages

localegen:
	django-admin makemessages -l da -i build -i dist -i "*egg*"

