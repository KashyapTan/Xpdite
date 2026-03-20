from mcp_servers.servers.description_format import build_tool_description


ADD_DESCRIPTION = build_tool_description(
    purpose="Add two numeric values and return their sum as a string.",
    use_when=(
        "You need straightforward addition for calculator-style workflows or "
        "quick arithmetic in a tool-calling sequence."
    ),
    inputs="a (float, required) and b (float, required).",
    returns=(
        "A string representation of the sum of a and b using Python's default "
        "float-to-string formatting."
    ),
    notes=(
        "This tool performs direct numeric addition only. It does not validate "
        "ranges or coerce non-numeric input."
    ),
)

DIVIDE_DESCRIPTION = build_tool_description(
    purpose=(
        "Divide one numeric value by another and return the quotient with up to "
        "50 decimal places."
    ),
    use_when=(
        "You need high-precision division output for deterministic arithmetic "
        "results in a text response."
    ),
    inputs="a (float, required) and b (float, required).",
    returns=(
        "A string containing a divided by b formatted with exactly 50 digits "
        "after the decimal point."
    ),
    notes=(
        "Division by zero is not handled in this wrapper and will raise the "
        "underlying Python exception."
    ),
)
