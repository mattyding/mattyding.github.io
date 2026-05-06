.PHONY: dev blog all

POSTS_DIR  = blog/posts
TEMPLATE   = blog/template.html
SOURCES    = $(wildcard $(POSTS_DIR)/*.md)
TARGETS    = $(SOURCES:.md=.html)

define open-browser
	(sleep 2 && python3 -m webbrowser -t "$(1)") &
endef

dev:
	$(call open-browser,http://localhost:8000) python3 -m http.server 8000

# Compile a single post: blog/posts/foo.md -> blog/posts/foo.html
$(POSTS_DIR)/%.html: $(POSTS_DIR)/%.md $(TEMPLATE)
	pandoc $< -o $@ \
		--template=$(TEMPLATE) \
		--mathjax \
		--syntax-highlighting=monochrome

# Build all posts, then regenerate the blog index
blog: $(TARGETS)
	python3 blog/build.py

all: blog
