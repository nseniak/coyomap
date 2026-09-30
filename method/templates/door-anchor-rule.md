**Where a step arriving through a door is anchored — one rule, for every agent that writes or reads
one.** A step that comes IN through an interface (`In → Cn`) is anchored at the `source` line of the
way in THIS step comes through, whatever that line looks like: a route line, a route decorator, a
tool handler's definition, a command's declaration. That line is where the request enters the
product, so it is the one step anchor that may sit on a definition header, and the checks accept it
there. Take the way in whose line leads to the step's own destination, not the use case's first one.
Two arrivals have no way in of their own:
- a click or an answer on a screen that is already open: anchor it where the screen's own code
  handles it (the click handler, the dialog's answer), never at the route that opened the page;
- a door someone else designs sending the person back (a sign-in provider's redirect): anchor it at
  our own way in that receives it.
A step going OUT (`Cn → In`) is anchored where the component delivers: the return, the render, the
write. A skeptic confirms a real arrival with that same line as its `evidence`, even when the work
happens further down: the work is the next step's claim, with its own anchor.
