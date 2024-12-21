.PHONY: dev open-url

define open-browser
	(sleep 2 && python3 -m webbrowser -t "$(1)") &
endef

dev:
	$(call open-browser,http://localhost:8000) python3 -m http.server 8000