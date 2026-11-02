"""Hand position to screen point, and when relative mode re-anchors.

The pointer lane and the preview both need exactly this step, and they used to
each carry their own copy of it — one in ``ControlEngine._map_pointer``, one in
``MainWindow._map_pointer``, with the re-anchor rule written twice. Two copies of
a rule that decides where the click lands is one copy too many, so it lives here
and both callers delegate.

The rule itself: an absolute mapper needs no anchor, but a relative mapper must
re-anchor after any pause or session boundary, and it must anchor on the *real*
native cursor rather than on the last mapping result. A physical mouse may have
moved during that pause, and re-anchoring on a stale value would make the first
frame of the new session jump by however far the mouse travelled.

Deliberately not a class. Both callers already own the strategy object, the
bounds and the pending flag; a wrapper would have to duplicate or proxy all
three, which is the problem this module exists to remove.
"""

from core.pointer_mapping import RelativeMapper


def project(mapper, bounds, pos, frame_size, *, anchor_pending=False, cursor_position=None):
    """Return the screen point for one camera position, re-anchoring if asked.

    ``cursor_position`` is an optional callable returning the real native pointer
    in screen points. It is only consulted for a relative mapper whose anchor is
    pending, because that is the only case where the current pointer matters.
    """
    if anchor_pending and isinstance(mapper, RelativeMapper):
        cursor = cursor_position() if callable(cursor_position) else None
        mapper.begin(pos, frame_size, bounds, cursor=cursor)
    return mapper.map(pos, frame_size, bounds)