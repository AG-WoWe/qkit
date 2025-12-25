import json
import math
import re
from typing import Sequence
from pathlib import Path

import matplotlib as mpl
import matplotlib.gridspec as gridspec
import matplotlib.pyplot as plt
from matplotlib.backends.backend_pgf import FigureCanvasPgf
from matplotlib.ticker import FuncFormatter, MaxNLocator


class HairyPlotter:
    ''' Styles: 'standart', 'thesis' '''
    # Load pgf backend to use only for pdf export
    mpl.backend_bases.register_backend('pdf', FigureCanvasPgf)

    def __init__(self, config_json, style='standard', figure_height=None):
        stylesheets, preambles, figure_path = self.read_config(config_json)
        plt.style.use(str(stylesheets[style]))
        self._style = style
        self.preambles = preambles
        self._fig_savepath = figure_path
        self.fig = None

        # For interactive plot, pdflatex is used and pgf can be used for export
        mpl.rcParams.update({
            "pgf.preamble": self.preambles['pgf'].read_text(),
            "text.latex.preamble": self.preambles['pdflatex'].read_text(),
        })
        if figure_height is not None:
            figsize = list(mpl.rcParams.get("figure.figsize", (6.4, 4.8)))
            figsize[1] = figure_height
            mpl.rcParams["figure.figsize"] = figsize

    def read_config(self, config_json):
        # Load stylesheets and Co
        with open (config_json, "r") as json_file:
            config = json.load(json_file)
            main_path = Path(config["main"])
            plot_conf_path = main_path / config["plot_config"]
            # get all stylesheets paths
            stylesheets = {s.split('.')[0]: plot_conf_path / s for s in config["stylesheets"]}
            preambles = {'pgf': plot_conf_path / config["preamble_pgf"],
                         'pdflatex': plot_conf_path / config["preamble_pdflatex"]}
            figure_path = main_path / config["figure_path"]
        return stylesheets, preambles, figure_path

    def create_figure(self, figure_height=None, **kwargs):
        """Create a bare figure, optionally overriding the height while keeping current width."""
        if figure_height is not None:
            default_figsize = mpl.rcParams.get("figure.figsize", (6.4, 4.8))
            fig_width = kwargs.get("figsize", default_figsize)[0]
            kwargs["figsize"] = (fig_width, figure_height)
        self.fig = plt.figure(**kwargs)
        return self.fig

    def create_subplots(self, *args, figure_height=None, **kwargs):
        if figure_height is not None:
            default_figsize = mpl.rcParams.get("figure.figsize", (6.4, 4.8))
            fig_width = kwargs.get("figsize", default_figsize)[0]
            kwargs["figsize"] = (fig_width, figure_height)
        self.fig, axs = plt.subplots(*args, **kwargs)
        return self.fig, axs

    def create_gridspec(self, gridspec_list):
        nrows = max(item['row_end'] for item in gridspec_list)
        ncols = max(item['col_end'] for item in gridspec_list)
        self.fig = plt.figure()
        print(nrows, ncols)
        gs = gridspec.GridSpec(nrows, ncols, figure=self.fig)
        axs = []
        for i, item in enumerate(gridspec_list):
            ax = self.fig.add_subplot(gs[item['row_start']:item['row_end'], item['col_start']:item['col_end']])
            axs.append(ax)
        return self.fig, axs

    def set_spacings(self, wspace=0, hspace=0):
        # Plot specific settings, especially when using multiple plots in one figure
        mpl.rcParams.update({
            "figure.constrained_layout.wspace": wspace,
            "figure.constrained_layout.hspace": hspace
        })

    def save_pdf(self, filename, **kwargs):
        self.fig.savefig(self._fig_savepath / filename, backend='pgf', **kwargs)

    def save_png(self, filename, **kwargs):
        if 'append_style' in kwargs:
            append_style = kwargs.pop('append_style')
            if append_style is True:
                filename_parts = filename.split('.')
                filename = '.'.join(filename_parts[:-1]) + f'_{self._style}.' + filename_parts[-1]
        self.fig.savefig(self._fig_savepath / filename, **kwargs)
    
    def add_testplot(self, axs):
        for ax in axs:
            ax.plot([0,1,2], [0,1,2], label='randomline')
            ax.set_ylabel(r'y-axis label (\si{mT/s})')
            ax.set_xlabel(r'\textbf{Figure 1.1:}')
            ax.legend()

    # --- SI prefix helpers -------------------------------------------------

    _SI_PREFIXES = {
        0: ("", ""),
        -3: ("m", "m"),
        -6: ("\u03bc", r"\textmu"),
        -9: ("n", "n"),
        -12: ("p", "p"),
        -15: ("f", "f"),
    }

    def auto_scale_axis(
        self,
        ax,
        axis="y",
        unit="",
        label=None,
        label_prefix=None,
        decimals=2,
        allowed_exponents=None,
    ):
        """
        Format an axis using SI prefixes (m, μ, n, p, f) and rescale tick labels.

        Parameters
        ----------
        ax : matplotlib.axes.Axes
            Target axes instance.
        axis : {'x', 'y'}, optional
            Which axis to format. Default is 'y'.
        unit : str, optional
            Unit string appended to the label (without prefix). For LaTeX/siunitx
            users, pass the unit macro, e.g. ``r'\\second'``.
        label : str, optional
            Full label string to start from (overrides the current axis label).
        label_prefix : str, optional
            Text placed before the unit. If omitted, the text preceding the first
            opening parenthesis of the current label is reused.
        decimals : int, optional
            Number of decimal places in tick labels.
        allowed_exponents : iterable of int, optional
            SI exponents to consider when picking a prefix. Defaults to
            ``[0, -3, -6, -9, -12, -15]``.

        Notes
        -----
        If the axis label already contains a unit wrapped in parentheses, the
        text within the outermost pair of parentheses is replaced with the
        newly computed prefix + unit combination.

        Returns
        -------
        dict
            Mapping containing the chosen ``'prefix'``, ``'exponent'`` and
            ``'scale'``.
        """

        axis = axis.lower()
        if axis not in {"x", "y"}:
            raise ValueError("axis must be either 'x' or 'y'")

        target_axis = ax.xaxis if axis == "x" else ax.yaxis
        vmin, vmax = target_axis.get_view_interval()
        max_abs = max(abs(vmin), abs(vmax))

        if allowed_exponents is None:
            allowed_exponents = [0, -3, -6, -9, -12, -15]
        allowed_exponents = sorted(set(allowed_exponents))

        if max_abs == 0:
            exponent = 0
        else:
            exponent = math.floor(math.log10(max_abs))

        candidates = [exp for exp in allowed_exponents if exp <= exponent]
        if candidates:
            chosen_exp = max(candidates)
        else:
            chosen_exp = min(allowed_exponents)

        scale = 10 ** chosen_exp
        text_prefix, tex_prefix = self._SI_PREFIXES.get(
            chosen_exp, ("", "")
        )

        def _format(value, _):
            scaled = value / scale if scale else value
            formatted = f"{scaled:.{decimals}f}".rstrip("0").rstrip(".")
            return formatted or "0"

        target_axis.set_major_formatter(FuncFormatter(_format))
        target_axis.set_major_locator(MaxNLocator(nbins="auto"))
        target_axis.get_offset_text().set_visible(False)
        target_axis.si_prefix = {
            "prefix": text_prefix,
            "tex_prefix": tex_prefix,
            "exponent": chosen_exp,
            "scale": scale,
        }

        base_label_full = label if label is not None else target_axis.get_label_text()
        base_label_full = base_label_full or ""
        if "(" in base_label_full and ")" in base_label_full:
            inferred_prefix = base_label_full[: base_label_full.find("(")].strip()
        else:
            inferred_prefix = base_label_full.strip()

        prefix_text = inferred_prefix
        if label_prefix is not None:
            prefix_text = label_prefix

        uses_tex = mpl.rcParams.get("text.usetex", False)
        if unit:
            prefix_for_label = tex_prefix if uses_tex else text_prefix
            new_unit_repr = (
                rf"{prefix_for_label}{unit}"
                if uses_tex
                else f"{prefix_for_label}{unit}".strip()
            )

            if prefix_text:
                if uses_tex:
                    new_label = rf"{prefix_text}\,({new_unit_repr})"
                else:
                    new_label = f"{prefix_text} ({new_unit_repr})".strip()
            else:
                new_label = new_unit_repr

            target_axis.set_label_text(new_label)
        elif label is not None:
            target_axis.set_label_text(base_label_full)

        return target_axis.si_prefix

    def auto_scale_axis_latex(
        self,
        ax,
        axis="y",
        unit="",
        label=None,
        decimals=2,
        allowed_exponents=None,
    ):
        """
        Like auto_scale_axis but replaces the first parenthesized unit inside the
        existing LaTeX/math label with the scaled unit prefix.
        """

        axis = axis.lower()
        if axis not in {"x", "y"}:
            raise ValueError("axis must be either 'x' or 'y'")

        target_axis = ax.xaxis if axis == "x" else ax.yaxis
        vmin, vmax = target_axis.get_view_interval()
        max_abs = max(abs(vmin), abs(vmax))

        if allowed_exponents is None:
            allowed_exponents = [0, -3, -6, -9, -12, -15]
        allowed_exponents = sorted(set(allowed_exponents))

        exponent = 0 if max_abs == 0 else math.floor(math.log10(max_abs))
        candidates = [exp for exp in allowed_exponents if exp <= exponent]
        chosen_exp = max(candidates) if candidates else min(allowed_exponents)

        scale = 10 ** chosen_exp
        text_prefix, tex_prefix = self._SI_PREFIXES.get(chosen_exp, ("", ""))

        def _format(value, _):
            scaled = value / scale if scale else value
            formatted = f"{scaled:.{decimals}f}".rstrip("0").rstrip(".")
            return formatted or "0"

        target_axis.set_major_formatter(FuncFormatter(_format))
        target_axis.set_major_locator(MaxNLocator(nbins="auto"))
        target_axis.get_offset_text().set_visible(False)
        target_axis.si_prefix = {
            "prefix": text_prefix,
            "tex_prefix": tex_prefix,
            "exponent": chosen_exp,
            "scale": scale,
        }

        base_label_full = label if label is not None else target_axis.get_label_text()
        base_label_full = base_label_full or ""
        uses_tex = mpl.rcParams.get("text.usetex", False)

        if unit:
            if uses_tex:
                # keep prefix+unit upright when inserted into a math label
                new_unit_repr = rf"\mathrm{{{tex_prefix}{unit}}}"
            else:
                new_unit_repr = f"{text_prefix}{unit}"

            def _repl(_match):
                return f"({new_unit_repr})"

            new_label, count = re.subn(r"\(([^()]*)\)", _repl, base_label_full, count=1)
            if count == 0:
                spacer = " " if base_label_full else ""
                new_label = f"{base_label_full}{spacer}({new_unit_repr})"
            target_axis.set_label_text(new_label)
        elif label is not None:
            target_axis.set_label_text(base_label_full)

        return target_axis.si_prefix

    # --- Panel / axes annotations -----------------------------------------

    def add_axes_text(
        self,
        ax,
        text,
        xy=(0.02, 0.98),
        fontweight=None,
        fontsize=None,
        **text_kwargs,
    ):
        """
        Add text positioned in axes coordinates.

        Parameters
        ----------
        ax : matplotlib.axes.Axes
            Target axes instance.
        text : str
            Letter or label to render.
        xy : tuple of float, optional
            (x, y) location in axes coordinates (default top-left inside frame).
        fontweight : str, optional
            Font weight. Defaults to inherited axes properties.
        fontsize : float, optional
            Font size; defaults to the y-label size when available.
        **text_kwargs :
            Extra keyword arguments forwarded to :meth:`Axes.text`.
        """
        if fontsize is None and ax.yaxis.label.get_text():
            fontsize = ax.yaxis.label.get_size()

        props = {
            "transform": ax.transAxes,
            "ha": "left",
            "va": "top",
        }
        if fontweight is not None:
            props["fontweight"] = fontweight
        if fontsize is not None:
            props["fontsize"] = fontsize
        props.update(text_kwargs)

        artist = ax.text(*xy, text, **props)
        ax.axes_text = artist
        return artist

    def add_figure_letter(
        self,
        ax,
        text,
        loc="top left",
        offset=(0.0, 0.0),
        fontweight="bold",
        fontsize=None,
        **text_kwargs,
    ):
        """
        Add a bold letter positioned relative to the full axes (including labels) in figure coordinates.

        Parameters
        ----------
        ax : matplotlib.axes.Axes
            The axes to annotate.
        text : str
            Character or string to place.
        loc : {'top left', 'top right', 'bottom left', 'bottom right'}, optional
            Anchor point on the axes' tight bounding box.
        offset : tuple of float, optional
            (dx, dy) offsets added in figure coordinates.
        fontweight : str, optional
            Font weight (default ``'bold'``).
        fontsize : float, optional
            Font size. Defaults to the y-label size if available.
        **text_kwargs :
            Extra keyword arguments forwarded to :func:`matplotlib.figure.Figure.text`.
        """
        fig = ax.figure
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()

        tight_bbox = ax.get_tightbbox(renderer)
        bbox_fig = tight_bbox.transformed(fig.transFigure.inverted())

        loc = loc.lower()
        if loc == "top left":
            x, y = bbox_fig.x0, bbox_fig.y1
            ha, va = "left", "top"
        elif loc == "top right":
            x, y = bbox_fig.x1, bbox_fig.y1
            ha, va = "right", "top"
        elif loc == "bottom left":
            x, y = bbox_fig.x0, bbox_fig.y0
            ha, va = "left", "bottom"
        elif loc == "bottom right":
            x, y = bbox_fig.x1, bbox_fig.y0
            ha, va = "right", "bottom"
        else:
            raise ValueError("loc must be one of 'top left', 'top right', 'bottom left', 'bottom right'")

        x += offset[0]
        y += offset[1]

        if fontsize is None and ax.yaxis.label.get_text():
            fontsize = ax.yaxis.label.get_size()

        props = {
            "transform": fig.transFigure,
            "ha": ha,
            "va": va,
            "fontweight": fontweight,
        }
        if fontsize is not None:
            props["fontsize"] = fontsize
        props.update(text_kwargs)

        artist = fig.text(x, y, text, **props)
        ax.figure_letter = artist
        return artist

    def add_aligned_figure_letters(
        self,
        axes: Sequence[plt.Axes],
        labels: Sequence[str],
        *,
        y_offset=0.0,
        fontweight="bold",
        fontsize=None,
        **text_kwargs,
    ):
        """
        Place figure letters for multiple axes using a shared vertical position.

        Parameters
        ----------
        axes : Sequence[matplotlib.axes.Axes]
            Axes to annotate.
        labels : Sequence[str]
            Corresponding panel labels.
        y_offset : float, optional
            Additional vertical shift applied (figure coordinates).
        fontweight : str, optional
            Font weight for the letters.
        fontsize : float, optional
            Font size to use. If ``None`` the y-label size of the first axes with
            a label is used.
        **text_kwargs :
            Additional keyword arguments passed to :func:`Figure.text`.
        """

        if len(axes) != len(labels):
            raise ValueError("axes and labels must have the same length")

        fig = axes[0].figure
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()

        tops = []
        xs = []
        for ax in axes:
            bbox = ax.get_tightbbox(renderer).transformed(fig.transFigure.inverted())
            tops.append(bbox.y1)
            xs.append(bbox.x0)

        target_y = min(tops) + y_offset

        if fontsize is None:
            for ax in axes:
                label = ax.yaxis.label
                if label.get_text():
                    fontsize = label.get_size()
                    break

        artists = []
        for ax, x, label in zip(axes, xs, labels):
            props = {
                "transform": fig.transFigure,
                "ha": "left",
                "va": "top",
                "fontweight": fontweight,
            }
            if fontsize is not None:
                props["fontsize"] = fontsize
            props.update(text_kwargs)
            artist = fig.text(x, target_y, label, **props)
            ax.figure_letter = artist
            artists.append(artist)

        return artists

    def add_aligned_figre_letters_test(  # pragma: no cover - helper for interactive notebooks
        self,
        axes: Sequence[plt.Axes],
        labels: Sequence[str],
        *,
        y_offset=0.0,
        fontweight="bold",
        fontsize=None,
        **text_kwargs,
    ):
        """
        Variant of :meth:`add_aligned_figure_letters` that keeps each label at the
        respective axis top edge instead of collapsing them onto a shared y-level.

        Parameters mirror the original helper. ``y_offset`` is applied per axis in
        figure coordinates so stacked panels remain separated vertically.
        """

        if len(axes) != len(labels):
            raise ValueError("axes and labels must have the same length")

        fig = axes[0].figure
        fig.canvas.draw()
        renderer = fig.canvas.get_renderer()

        xs = []
        ys = []
        for ax in axes:
            bbox = ax.get_tightbbox(renderer).transformed(fig.transFigure.inverted())
            xs.append(bbox.x0)
            ys.append(bbox.y1)

        if fontsize is None:
            for ax in axes:
                label = ax.yaxis.label
                if label.get_text():
                    fontsize = label.get_size()
                    break

        artists = []
        for ax, x, y, label in zip(axes, xs, ys, labels):
            props = {
                "transform": fig.transFigure,
                "ha": "left",
                "va": "top",
                "fontweight": fontweight,
            }
            if fontsize is not None:
                props["fontsize"] = fontsize
            props.update(text_kwargs)
            artist = fig.text(x, y + y_offset, label, **props)
            ax.figure_letter = artist
            artists.append(artist)

        return artists


    if __name__ == "__main__":
        pass
