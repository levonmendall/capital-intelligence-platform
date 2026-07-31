"""Adapt the immutable PR264 apply script to the current production evidence loop."""

from pathlib import Path


def main() -> None:
    path = Path("tools/apply_comprehensive_market_discovery.py")
    lines = path.read_text(encoding="utf-8").splitlines()
    marker = '        label="use dynamic direct client universe",'
    matches = [index for index, line in enumerate(lines) if line == marker]
    if len(matches) != 1:
        raise RuntimeError(f"dynamic direct-client marker count is {len(matches)}")

    marker_index = matches[0]
    start = next(
        index
        for index in range(marker_index, -1, -1)
        if lines[index] == "    content = replace_once("
    )
    end = next(
        index
        for index in range(marker_index + 1, len(lines))
        if lines[index] == "    )"
    )
    replacement = [
        "    content = replace_once(",
        "        content,",
        "        '''    if direct_instruments:",
        "        direct_client = DirectGlobalMarketClient()",
        "        for instrument in direct_instruments:''',",
        "        '''    if direct_instruments:",
        "        direct_client = DirectGlobalMarketClient(",
        "            DirectGlobalMarketUniverse(",
        '                identifier=f"dynamic-direct-evidence:{universe.identifier}",',
        '                provider_identifier="comprehensive-direct-market-evidence.v1",',
        "                instruments=direct_instruments,",
        "                limitations=universe.limitations,",
        "            )",
        "        )",
        "        for instrument in direct_instruments:''',",
        '        label="use dynamic direct client universe",',
        "    )",
    ]
    lines[start : end + 1] = replacement
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
