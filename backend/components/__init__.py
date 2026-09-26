"""IFC components: files a user attaches to a project (a staircase, a kitchen island, a vendor's
furniture) that the model can place into the design as opaque, rigid objects.

- `assets.py` normalises an upload (IFC4, metres), finds its products and measures them.
- `store.py` keeps them per project (files under output/projects/<id>/components/, rows in SQLite).
- `ifc/components.py` copies a placed component's products into the compiled model.
"""
