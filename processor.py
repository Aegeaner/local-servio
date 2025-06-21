import re
from markdown.extensions import Extension
from markdown.preprocessors import Preprocessor
from markdown.postprocessors import Postprocessor


class MathPreprocessor(Preprocessor):
    MATH_BLOCK_REGEX = re.compile(
        r"(\$\$.*?\$\$|\$[^$\n]+?\$|\\\[.*?\\\]|\\\(.*?\\\))", re.DOTALL
    )

    def __init__(self, md):
        super().__init__(md)
        self.math_blocks = []

    def run(self, lines):
        text = "\n".join(lines)

        def repl(m):
            self.math_blocks.append(m.group(0))
            return f"@@MATH_BLOCK_{len(self.math_blocks) - 1}@@"

        text = self.MATH_BLOCK_REGEX.sub(repl, text)
        return text.split("\n")


class MathPostprocessor(Postprocessor):
    def __init__(self, math_blocks):
        super().__init__()
        self.math_blocks = math_blocks

    def run(self, text):
        for i, block in enumerate(self.math_blocks):
            text = text.replace(f"@@MATH_BLOCK_{i}@@", block)
        return text


class MathProtectExtension(Extension):
    def extendMarkdown(self, md):
        preprocessor = MathPreprocessor(md)
        md.preprocessors.register(preprocessor, "math_pre", 25)
        md.postprocessors.register(
            MathPostprocessor(preprocessor.math_blocks), "math_post", 25
        )
