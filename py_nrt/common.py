def run_from_ipython():  # pragma: no cover
    """
    Returns True if function was called from ipython, used in pretty ipython
        notebook printing
    """
    try:
        __IPYTHON__
        return True
    except NameError:
        return False
