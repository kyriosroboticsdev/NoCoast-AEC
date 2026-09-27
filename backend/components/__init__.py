"""IFC files attached to a prompt as components: each becomes a brick in the design's own library.

    attachment (schemas side)  ->  convert.to_brick  ->  Design.library  ->  placed with a `brick` step

Nothing else in the pipeline knows a component from any other brick: placement, clash checks, the
look loop, the compiler and the lifter all see an asset with mesh geometry.
"""

from components.attachment import MAX_COMPONENTS, IfcAttachment
from components import convert
from components.convert import ComponentError, attach, component_lines, to_brick

__all__ = ["MAX_COMPONENTS", "ComponentError", "IfcAttachment", "attach", "component_lines", "convert", "to_brick"]
