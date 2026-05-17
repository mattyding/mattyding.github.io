.PHONY: dev blog all editor

POSTS_DIR  = blog/posts
TEMPLATE   = blog/template.html

SOURCES_MD  = $(wildcard $(POSTS_DIR)/*.md)
SOURCES_TEX = $(wildcard $(POSTS_DIR)/*.tex)
TARGETS     = $(SOURCES_MD:.md=.html) $(SOURCES_TEX:.tex=.html)

define open-browser
	(sleep 2 && python3 -m webbrowser -t "$(1)") &
endef

dev:
	$(call open-browser,http://localhost:8000) python3 -m http.server 8000

editor:
	python3 editor.py

# Compile a markdown post: blog/posts/foo.md -> blog/posts/foo.html
$(POSTS_DIR)/%.html: $(POSTS_DIR)/%.md $(TEMPLATE)
	pandoc $< -o $@ \
		--template=$(TEMPLATE) \
		--mathjax \
		--syntax-highlighting=monochrome

# Compile a LaTeX post: blog/posts/foo.tex -> blog/posts/foo.html
$(POSTS_DIR)/%.html: $(POSTS_DIR)/%.tex $(TEMPLATE)
	python3 blog/tex2html.py $< $@

# Build all posts, then regenerate the blog index
blog: $(TARGETS)
	python3 blog/build.py

all: blog
