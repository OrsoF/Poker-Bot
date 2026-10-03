"""Read visible six-max seats and stacks; locate positions from the dealer D."""

from math import atan2

from src.models import SeatObservation


SIX_MAX_POSITIONS = ("BTN", "SB", "BB", "UTG", "HJ", "CO")


def read_seats(page, layout) -> tuple[SeatObservation, ...]:
    """Use rendered name/stack pairs and calibrated hero cards, never ACTION."""
    if len(layout.hero) != 2 or any(region.width <= 0 or region.height <= 0 for region in layout.hero):
        return ()
    geometry = page.locator("body").evaluate(
        r"""(body, regions) => {
          const visible = (element) => {
            const r = element.getBoundingClientRect(), s = getComputedStyle(element);
            if (r.width <= 0 || r.height <= 0 || s.display === 'none'
                || s.visibility === 'hidden') return false;
            for (let parent = element; parent; parent = parent.parentElement) {
              if (Number(getComputedStyle(parent).opacity) === 0) return false;
            }
            return true;
          };
          const point = (element) => {
            const r = element.getBoundingClientRect();
            return [r.x + r.width / 2, r.y + r.height / 2];
          };
          // React Native Web renders an image as a CSS background plus an
          // opacity-zero img. Accept that background only when it is visible.
          const images = Array.from(body.querySelectorAll('img')).map(image => {
            const source = image.getAttribute('src');
            const parent = image.parentElement;
            const background = parent && Array.from(parent.children).find(child =>
              child !== image && visible(child) && source
              && getComputedStyle(child).backgroundImage.includes(source));
            return {source, element: visible(image) ? image : background};
          }).filter(image => image.element);
          const tables = images.filter(image => image.source?.includes('/poker/table/'));
          if (tables.length !== 1) return null;
          const r = tables[0].element.getBoundingClientRect();
          const inside = ([x, y]) => x >= r.x - r.width * .25 && x <= r.right + r.width * .25
            && y >= r.y - r.height * .25 && y <= r.bottom + r.height * .25;
          const amount = /^\d+(?:\.\d+)?(?:\s*BB)?$/i;
          const action = /^(?:ACTION|FOLD|CHECK|CALL(?:\s+.*)?|BET(?:\s+.*)?|RAISE(?:\s+.*)?|ALL[- ]IN(?:\s+.*)?)$/i;
          const pairLines = (element) => {
            const lines = (element.innerText || '').trim().split(/\n+/).map(s => s.trim()).filter(Boolean);
            if (lines.length === 3 && action.test(lines[0])) lines.shift();
            return lines;
          };
          const elements = Array.from(body.querySelectorAll('*')).filter(visible);
          const players = [];
          for (const element of elements) {
            if (element.closest('button, [role="button"], input')) continue;
            const lines = pairLines(element);
            if (lines.length !== 2 || !amount.test(lines[1]) || amount.test(lines[0])
                || action.test(lines[0])) continue;
            // Normalize badges on both sides to keep the smallest container.
            const children = Array.from(element.querySelectorAll('*')).filter(visible);
            if (children.some(child => pairLines(child).join('\n') === lines.join('\n'))) continue;
            const name = children.find(child => (child.innerText || '').trim() === lines[0]);
            const p = point(name || element);
            let folded = false;
            for (let parent = element, depth = 0; parent && depth < 4; parent = parent.parentElement, depth++) {
              const text = (parent.innerText || '').trim().split(/\n+/).map(s => s.trim()).filter(Boolean);
              if (text.length === 3 && text[1] === lines[0] && text[2] === lines[1] && action.test(text[0])) {
                folded = text[0] === 'FOLD';
                break;
              }
              if (text.length > 3) break;
            }
            if (inside(p)) players.push({name: lines[0], stack: Number(lines[1].replace(/\s*BB$/i, '')), point: p, folded});
          }
          const left = Math.min(...regions.map(a => a[0])) * innerWidth;
          const right = Math.max(...regions.map(a => a[0] + a[2])) * innerWidth;
          const top = Math.min(...regions.map(a => a[1])) * innerHeight;
          const bottom = Math.max(...regions.map(a => a[1] + a[3])) * innerHeight;
          const hero = [(left + right) / 2, (top + bottom) / 2];
          const stacks = elements.filter(element => {
            const text = (element.innerText || '').trim(), p = point(element);
            return amount.test(text) && !element.closest('button, [role="button"], input')
              && !Array.from(element.children).some(child => visible(child) && (child.innerText || '').trim() === text)
              && p[0] >= left - innerWidth * .05 && p[0] <= right + innerWidth * .05
              && p[1] >= bottom && p[1] <= bottom + innerHeight * .12;
          });
          const heroFolded = elements.some(element => {
            const p = point(element);
            return (element.innerText || '').trim() === 'FOLD'
              && p[0] >= left - innerWidth * .05 && p[0] <= right + innerWidth * .05
              && p[1] >= top && p[1] <= bottom + innerHeight * .12;
          });
          return {bounds: [r.x, r.y, r.width, r.height], players, hero,
            heroStack: stacks.length === 1 ? Number(stacks[0].innerText.trim().replace(/\s*BB$/i, '')) : null,
            heroFolded,
            buttons: images.filter(image => image.source?.includes('dealer-button')).map(image => point(image.element))};
        }""",
        [[region.x, region.y, region.width, region.height] for region in layout.hero],
    )
    return seats_from_geometry(geometry)


def seats_from_geometry(geometry) -> tuple[SeatObservation, ...]:
    """Assign positions only for a complete, unambiguous six-seat ring."""
    if geometry is None:
        return ()
    x, y, width, height = geometry["bounds"]
    if width <= 0 or height <= 0:
        return ()

    def normalized(point):
        return ((point[0] - x) / width, (point[1] - y) / height)

    def distance(first, second):
        return ((first[0] - second[0]) ** 2 + (first[1] - second[1]) ** 2) ** .5

    hero = normalized(geometry["hero"])
    players = [dict(player, point=normalized(player["point"]), is_hero=False)
               for player in geometry["players"]]
    # A named hero can be read from the same rendered pair as the opponents.
    nearby = [player for player in players if distance(player["point"], hero) <= .20]
    if len(nearby) > 1:
        return ()
    if nearby:
        nearby[0]["is_hero"] = True
    else:
        players.append({"name": None, "stack": geometry["heroStack"], "point": hero,
                        "is_hero": True, "folded": geometry.get("heroFolded", False)})
    if len(players) != 6:
        return ()
    if any(distance(a["point"], b["point"]) < .10
           for index, a in enumerate(players) for b in players[index + 1:]):
        return ()
    if any(distance(player["point"], (.5, .5)) < .20 for player in players):
        return ()

    players.sort(key=lambda player: atan2(player["point"][1] - .5, player["point"][0] - .5))
    top = min(range(6), key=lambda index: players[index]["point"][1])
    players = players[top:] + players[:top]
    # atan2 increases clockwise in screen coordinates (the y axis points down).
    dealer = None
    if len(geometry["buttons"]) == 1:
        button = normalized(geometry["buttons"][0])
        distances = sorted((distance(player["point"], button), index)
                           for index, player in enumerate(players))
        if distances[0][0] <= .25 and distances[1][0] - distances[0][0] >= .04:
            dealer = distances[0][1]
    return tuple(
        SeatObservation(
            seat_index=index, name=player["name"], stack_bb=player["stack"],
            position=SIX_MAX_POSITIONS[(index - dealer) % 6] if dealer is not None else None,
            is_hero=player["is_hero"], is_dealer=index == dealer,
            folded=player.get("folded", False),
        )
        for index, player in enumerate(players)
    )
