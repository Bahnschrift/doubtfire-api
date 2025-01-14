# Copyright 2020-2024 Facundo Batista
# All Rights Reserved
# Licensed under Apache 2.0

"""USAGE: jupynote.py notebook.ipynb cells

    cells is a string with which cells to include, separate groups
    with comma, ranges with dash (with defaults to start and end.
"""

import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import textwrap
import traceback


# basic verbatim start/end
VERBATIM_BEGIN = [r"\begin{footnotesize}", r"\begin{verbatim}"]
VERBATIM_END = [r"\end{verbatim}", r"\end{footnotesize}"]

# highlighers for different languages (block beginning and ending)
HIGHLIGHTERS = {
    'python': ([r'\begin{minted}[fontsize=\footnotesize]{python}'], [r'\end{minted}']),
    None: (VERBATIM_BEGIN, VERBATIM_END),
}

# the different formats to be used when error or all ok
FORMAT_ERROR = r"colback=red!5!white,colframe=red!75!"
FORMAT_OK = (
    r"coltitle=red!75!black, colbacktitle=black!10!white, "
    r"halign title=right, fonttitle=\sffamily\mdseries\scshape\footnotesize")

# a little mark to put in the continuation line(s) when text is wrapped
WRAP_MARK = "↳"

# the options available for command line
CMDLINE_OPTION_NAMES = [
    "output-text-limit",
]


def _validator_positive_int(value):
    """Validate value is a positive integer."""
    value = value.strip()
    if not value:
        return

    value = int(value)
    if value <= 0:
        raise ValueError("Value must be greater than zero.")
    return value


def _process_plain_text(lines, config_options=None):
    """Wrap a series of lines around a verbatim indication."""
    if config_options is None:
        config_options = {}

    result = []
    result.extend(VERBATIM_BEGIN)
    for line in lines:
        line = line.strip()

        # clean color escape codes (\u001b plus \[Nm where N are one or more digits)
        line = re.sub(r"\x1b\[[\d;]+m", "", line)

        # split too long lines
        limit = config_options.get("output-text-limit")
        if limit and line:
            firstline, *restlines = textwrap.wrap(line, limit)
            lines = [firstline]
            for line in restlines:
                lines.append(f"    {WRAP_MARK} {line}")
        else:
            lines = [line]

        result.extend(lines)
    result.extend(VERBATIM_END)
    return result


class ItemProcessor:
    """Process each item according to its type with a (series of) function(s)."""

    def __init__(self, cell_options, config_options):
        self.cell_options = cell_options
        self.config_options = config_options

    def get_item_data(self, item):
        """Extract item information using different processors."""

        data = item['data']
        for mimetype, *functions in self.PROCESSORS:
            if mimetype in data:
                content = data[mimetype]
                break
        else:
            raise ValueError("Image type not supported: {}".format(data.keys()))

        for func in functions:
            content = func(self, content)

        return content

    def process_plain_text(self, lines):
        """Process plain text."""
        return _process_plain_text(lines, self.config_options)

    def process_png(self, image_data):
        """Process a PNG: just save the received b64encoded data to a temp file."""
        _, fname = tempfile.mkstemp(suffix='.png')
        with open(fname, 'wb') as fh:
            fh.write(base64.b64decode(image_data))
        return fname

    def process_svg(self, image_data):
        """Process a SVG: save the data, transform to PDF, and then use that."""
        _, svg_fname = tempfile.mkstemp(suffix='.svg')
        _, pdf_fname = tempfile.mkstemp(suffix='.pdf')
        raw_svg = ''.join(image_data).encode('utf8')
        with open(svg_fname, 'wb') as fh:
            fh.write(raw_svg)

        cmd = ['rsvg-convert', '--format=pdf', '--output={}'.format(pdf_fname), svg_fname]
        subprocess.run(cmd)

        return pdf_fname

    def include_graphics(self, fname):
        """Wrap a filename in an includegraphics structure."""
        fname_no_backslashes = fname.replace("\\", "/")  # do not leave backslashes in Windows
        width = self.cell_options.get("output-image-size", r"1\textwidth")
        return r"\includegraphics[width={}]{{{}}}".format(width, fname_no_backslashes)

    def listwrap(self, item):
        """Wrap an item in a list for processors that return that single item."""
        return [item]

    # mimetype and list of functions to apply; order is important here as we want to
    # prioritize getting some mimetypes over others when multiple are present
    PROCESSORS = [
        ('text/latex',),
        ('image/svg+xml', process_svg, include_graphics, listwrap),
        ('image/png', process_png, include_graphics, listwrap),
        ('text/plain', process_plain_text),
    ]


class Notebook:
    """The notebook converter to latex."""

    GLOBAL_CONFIGS = {
        "output-text-limit": _validator_positive_int,
    }

    def __init__(self, path, config_options):
        self.config_options = self._validate_config(config_options)
        self.cell_options = {}

        with open(path, 'rt', encoding='utf8') as fh:
            nb_data = json.load(fh)

        # get the languaje, to highlight
        lang = nb_data['metadata']['language_info']['name']
        self._highlight_delimiters = HIGHLIGHTERS.get(lang, HIGHLIGHTERS[None])

        # get all cells excluding markdown ones
        self._cells = [x for x in nb_data['cells'] if x['cell_type'] != 'markdown']

    def _validate_config(self, config):
        """Validate received configuration."""
        for key, value in list(config.items()):
            validator = self.GLOBAL_CONFIGS[key]
            new_value = validator(value)
            config[key] = new_value
        return config

    def _proc_src(self, content):
        """Process the source of a cell."""
        source = content['source']
        result = []
        if content['cell_type'] == 'code':
            begin, end = self._highlight_delimiters
            result.extend(begin)
            result.extend(textwrap.fill(line[:1000] + ' [The rest of this line has been truncated by the system to improve readability.] ' * (len(line) > 1000), width=90, subsequent_indent='    ') for line in source)
            result.extend(end)
        else:
            raise ValueError(
                "Cell type not supported when processing source: {!r}".format(
                    content['cell_type']))

        return '\n'.join(result)

    def _proc_out(self, content):
        """Process the output of a cell."""
        outputs = content.get('outputs')
        if not outputs:
            return

        result = []
        processor = ItemProcessor(self.cell_options, self.config_options)
        for item in outputs:
            output_type = item['output_type']
            if output_type in ('execute_result', 'display_data'):
                more_content = processor.get_item_data(item)
            elif output_type == 'stream':
                more_content = processor.process_plain_text(item["text"])
            elif output_type == 'error':
                raw_traceback = item['traceback']
                tback_lines = []
                for raw_line in raw_traceback:
                    internal_lines = raw_line.split('\n')
                    for line in internal_lines:
                        line = re.sub(r"\x1b\[\d.*?m", "", line)  # sanitize
                        if set(line) == {'-'}:
                            # ignore separator, as our graphical box already has one
                            continue
                        tback_lines.append(line)
                more_content = processor.process_plain_text(tback_lines)
            else:
                raise ValueError("Output type not supported in item {!r}".format(item))
            result.extend(more_content)

        return '\n'.join(result)

    def get(self, cell_idx):
        """Return the content from a specific cell in the notebook.

        The content is already splitted in source and output, and converted to latex.
        """
        content = self._cells[cell_idx - 1]
        source = self._proc_src(content)
        output = self._proc_out(content)
        return source, output

    def parse_cells(self, spec):
        """Convert the cells spec to a range of ints."""
        if not spec:
            raise ValueError("Empty cells spec not allowed")

        maxlen = len(self._cells)

        cells = set()
        options = {}
        groups = [x.strip() for x in spec.split(',')]
        valid_chars = set('0123456789-,')
        for group in groups:
            if '=' in group:
                k, v = group.split("=", maxsplit=1)
                options[k] = v
                continue

            if set(group) - valid_chars:
                raise ValueError(
                    "Found forbidden characters in cells definition (allowed digits, '-' and ',')")

            if '-' in group:
                cfrom, cto = group.split('-')
                cfrom = 1 if cfrom == '' else int(cfrom)
                cto = maxlen if cto == '' else int(cto)
                if cfrom > cto:
                    raise ValueError(
                        "Range 'from' needs to be equal to or smaller than 'to' (got {!r})".format(group))
                cells.update(range(cfrom, cto + 1))
            else:
                cells.add(int(group))
        cells = sorted(cells)

        if any(x < 1 for x in cells):
            raise ValueError("Cells need to be >=1")
        if maxlen < cells[-1]:
            raise ValueError(
                f"Notebook loaded of len {maxlen}, smaller than requested cells: {cells}")

        self.cell_options = options
        return cells


def main(notebook_path, cells_spec, config_options):
    """Main entry point."""
    nb = Notebook(notebook_path, config_options)
    cells = nb.parse_cells(cells_spec)

    for cell in cells:
        try:
            src, out = nb.get(cell)
        except Exception:
            title = "ERROR when parsing cell {}".format(cell)
            print(r"\begin{{tcolorbox}}[{}, title={{{}}}]".format(FORMAT_ERROR, title))
            tb = traceback.format_exc()
            _parts = _process_plain_text(tb.split('\n'))
            print('\n'.join(_parts))
            print(r"\end{tcolorbox}")
            continue

        print(r"\begin{{tcolorbox}}[{}, title=Cell {{{:02d}}}]".format(FORMAT_OK, cell))
        print(src)
        if out:
            print(r"\tcblower")
            print(out)
        print(r"\end{tcolorbox}")


if __name__ == "__main__":
    if len(sys.argv) != 3 + len(CMDLINE_OPTION_NAMES):
        print(__doc__)
        exit()

    notebook_path, cells_spec, *option_values = sys.argv[1:4]
    config_options = dict(zip(CMDLINE_OPTION_NAMES, option_values))

    main(notebook_path, cells_spec, config_options)
