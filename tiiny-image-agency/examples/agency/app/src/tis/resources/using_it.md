# Using this page

**Make** is where a picture gets made. Describe the artefact, not the
aesthetic — "app icon, transparent background" routes to a model that
can do that; "nice modern fox" does not, because the resolver filters
on artefact words, not adjectives. The model badge above says which
model was chosen and why, before anything is spent on it.

**The NPU meter** is the one honest number on the page. The appliance
is a single shared inference pool, and loading a model evicts whatever
was resident — a job that needs a swap costs tens of seconds before it
has made anything. The meter says what is loaded right now, and if the
appliance did not answer it says that too, rather than guessing.

**The judge always sees the picture.** The critic that reviews a
result is a vision model, not a text model that is only shown the
prompt — a text-only judge invents defects it never looked at. Read
what it says before trying again: a second attempt with the critique
applied beats a third blind one.

**Models** is the catalogue: every model the appliance can generate
with, what it costs in NPU, and what it was *measured* to do — not
just what it advertises. A model's card separates the advertised
claim from the measured fact, because the two do not always agree.

**References** save a result with the recipe that made it — its
model, its dialect, its size, its requirements — so the next picture
can be told to come out like it. That is how a repeated job stays a
repeated job instead of a fresh roll each time.

**Drag an image onto the drop zone** to edit it rather than make a new
one. Whether a model actually uses the source picture, ignores it, or
refuses it outright is a measured fact on its card — not every model
that accepts an image does anything with it.

**API**, the other half of this tab, is for building against the
agency rather than clicking through it: the live schema, and a console
to try a call.
