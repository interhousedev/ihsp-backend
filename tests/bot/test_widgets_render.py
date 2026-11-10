"""OpenUI blocks as Telegram widgets: escaping, limits and the fallback."""

from app.interfaces.bot.widgets.deliver import plan_widgets
from app.interfaces.bot.widgets.render import SCRIPT, audit, render_widget

EVIL = "Tom & Jerry's"
TABLE = 'root = Stack([t])\nt = Table(["Day", "Mark"], [["Mon", 5], ["Tue", 4]])\n'


def test_table_renders_with_theme_variables() -> None:
    widget = render_widget(TABLE)
    assert widget is not None
    assert "--tg-theme-text-color" in widget.html
    assert audit(widget.html)
    assert "<td>Mon</td>" in widget.html


def test_model_text_is_escaped_in_every_component() -> None:
    source = (
        "root = Stack([c, s, g, b, p, l])\n"
        f'c = Card("{EVIL}", [TextBlock("{EVIL}")])\n'
        f's = StatGrid([{{label: "a", value: "{EVIL}"}}])\n'
        'g = Table(["x"], [["y"]])\n'
        'b = BarChart(["a", "b"], [1, 2])\n'
        'p = Progress("p", 1, 2)\n'
        'l = LinkList([{title: "t", url: "https://example.com/a"}])\n'
    )
    widget = render_widget(source)
    assert widget is not None
    assert "Tom & Jerry" not in widget.html
    assert "Tom &amp; Jerry&#x27;s" in widget.html
    assert widget.html.count("<script") == SCRIPT.count("<script")


def test_https_link_becomes_a_button_others_stay_text() -> None:
    source = (
        'root = LinkList([{title: "ok", url: "https://example.com/a"},'
        ' {title: "tg", url: "https://t.me/x"}])\n'
    )
    widget = render_widget(source)
    assert widget is not None
    assert widget.html.count("data-url=") == 1
    assert "t.me" not in widget.html


def test_invalid_block_has_no_widget() -> None:
    assert render_widget("root = Nope(1)\n") is None


def test_too_tall_block_falls_back() -> None:
    rows = ", ".join('["a", "b"]' for _ in range(30))
    source = f'root = Table(["x", "y"], [{rows}])\n'
    assert render_widget(source) is None


def test_request_button_carries_the_token() -> None:
    widget = render_widget(TABLE, viz_token="0123456789abcdef", visualize_label="See")
    assert widget is not None
    assert 'data-req="viz:0123456789abcdef"' in widget.html


def test_audit_rejects_network_and_handlers() -> None:
    for bad in (
        "<p>https://evil.example/x</p>",
        '<p onclick="x()">',
        "<style>a{background:url(x)}</style>",
        '<script src="x"></script>',
    ):
        assert not audit(bad)


def test_plan_keeps_text_and_is_all_or_nothing() -> None:
    body = f"Marks:\n```openui\n{TABLE}```\nBye"
    plan = plan_widgets(body, viz_token=None, visualize_label="")
    assert plan is not None
    assert plan.text.startswith("Marks:") and plan.text.endswith("Bye")
    assert len(plan.blocks) == 1
    assert plan_widgets("Plain text", viz_token=None, visualize_label="") is None
