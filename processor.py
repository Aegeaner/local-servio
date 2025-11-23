import re
from markdown.extensions import Extension
from markdown.preprocessors import Preprocessor
from markdown.postprocessors import Postprocessor


class MathPreprocessor(Preprocessor):
    # A more robust regex for LaTeX math blocks.
    # Now includes patterns for inline $...$ (single and double $$), and \[...\] / \(...).
    # Also attempts to capture standalone LaTeX commands (like \Sigma, \mod) as math.
    MATH_BLOCK_REGEX = re.compile(
        r"(\\[(?:equation|align|gather|split|multline)\][\\s\\S]*?\\\[(?:equation|align|gather|split|multline)\]|\\[\\(.*?\\)\\]|\\\\.*?\\\\|$$\\$.*?$$\\$\\|$$[^\\n]*?$$|\\\\[a-zA-Z]+\\\\)", re.DOTALL
    )

    def __init__(self, md=None): # md can be None as we run it manually
        super().__init__(md)
        self.math_blocks = []

    def run(self, lines):
        text = "\n".join(lines)

        def repl(m):
            self.math_blocks.append(m.group(0))
            return f"@@MATH_BLOCK_{len(self.math_blocks) - 1}@@"

        text = self.MATH_BLOCK_REGEX.sub(repl, text)
        return text.split("\n")


class MathPostprocessor:
    def __init__(self, math_blocks):
        self.math_blocks = math_blocks

    def run(self, text):
        # Use re.sub to allow for flexible matching of placeholders (e.g., with extra spaces)
        for i, block in enumerate(self.math_blocks):
            # Match the placeholder with optional leading/trailing whitespace
            placeholder_pattern = re.compile(r'\\s*@@MATH_BLOCK_{}\\s*' .format(i))
            text = placeholder_pattern.sub(block, text)
        return text


class MathProtectExtension(Extension):
    def extendMarkdown(self, md):
        preprocessor = MathPreprocessor(md)
        md.preprocessors.register(preprocessor, "math_pre", 25)
        md.postprocessors.register(
            MathPostprocessor(preprocessor.math_blocks), "math_post", 25
        )


class ListFixPreprocessor(Preprocessor):
    """
    Aggressively fixes malformed unordered lists where multiple items are on a single line,
    especially those starting with introductory text followed by " - Item1 - Item2...".
    This preprocessor aims to transform such lines into standard Markdown unordered lists
    with proper line breaks and list item markers, preserving original indentation.
    It also handles cases where a hyphen is immediately followed by content (e.g., "-Item").
    Crucially, it now correctly handles nesting within ordered lists by ensuring proper block separation
    by inserting a blank line between the ordered list item content and the nested unordered list,
    while maintaining correct indentation.
    """
    LIST_ITEM_SEPARATOR_REGEX = re.compile(r" \s-\s ") # Matches ' - '

    def run(self, lines):
        new_lines = []
        for line in lines:
            original_indent = re.match(r"^\\s*", line).group(0)
            content_without_indent = line[len(original_indent):]

            # Case 1: Line content starts with a hyphen immediately followed by a non-whitespace character
            # e.g., "  -Item" -> "  - Item"
            if re.match(r"^-(\\S)", content_without_indent):
                fixed_content = "- " + content_without_indent[1:]
                new_lines.append(original_indent + fixed_content)
                continue

            # Case 2: Line content contains multiple list items separated by ' - '
            # and is NOT already a well-formed unordered list item.
            is_potential_split_line = self.LIST_ITEM_SEPARATOR_REGEX.search(content_without_indent) and \
                                      not re.match(r"^(?:- |\* |\+ )", content_without_indent)

            if is_potential_split_line:
                parts = self.LIST_ITEM_SEPARATOR_REGEX.split(content_without_indent)

                # Check if the first part is an ordered list item
                ordered_list_match = re.match(r"^(\\d+\\.)\\s*(.*)", parts[0].strip())
                
                if ordered_list_match:
                    # If it's an ordered list item, keep its original prefix and content
                    # And then add a blank line with indentation to clearly separate it from the nested unordered list
                    new_lines.append(original_indent + ordered_list_match.group(1) + " " + ordered_list_match.group(2).strip())
                    nested_indent = original_indent + "    " # Indent 4 spaces for nested unordered list
                    if len(parts) > 1: # Only add blank line if there are nested items to follow
                        new_lines.append(nested_indent + "") # Insert blank line with indentation
                elif parts[0].strip(): # Not an ordered list, but has introductory text
                    new_lines.append(original_indent + parts[0].strip())
                    nested_indent = original_indent + "    " # Default 4 spaces indent for nested list under paragraph
                    if len(parts) > 1: # Only add blank line if there are nested items to follow
                        new_lines.append(nested_indent + "") # Insert blank line with indentation
                else:
                    nested_indent = original_indent + "    " # Default if no intro text
                    if len(parts) > 1 and not new_lines: # If this is the very first line and has nested items
                         new_lines.append("") # Add a blank line to start the block
                         
                # Add the rest of the parts as properly formatted unordered list items
                for part in parts[1:]:
                    if part.strip():
                        new_lines.append(nested_indent + "- " + part.strip())
            else:
                new_lines.append(line)
        return new_lines


class ListFixExtension(Extension):
    def extendMarkdown(self, md):
        # Register with a very low priority to run very early, before other Markdown preprocessors
        md.preprocessors.register(ListFixPreprocessor(md), "list_fix", 15)