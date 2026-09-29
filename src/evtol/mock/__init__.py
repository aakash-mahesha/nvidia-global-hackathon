"""The rig mock — a program that convincingly pretends to be the rig.

No model, no physics, no robot. It publishes the same messages on the same
topics at the same rates the real rig will, so the console and the permit
reasoner at site 2 can be built and tested weeks before there is an arm to
plug in — and so CI can replay a run without hardware.

The contract requirement (docs/CONTRACTS.md §5) is that **the console must not
be able to tell the difference**. Every field the mock publishes must be one
the real rig will publish, spelled identically. The moment the mock has a
field the rig will not have, or vice versa, there are two systems instead of
one — and that is discovered in week 3, on the worst possible evening.

    python -m evtol.mock.publisher            # fake arm onto the bus, 20 Hz
"""
