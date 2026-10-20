from .cli import main
from .state import Error
try:
    main()
except Error as error:
    import json
    import sys
    print(json.dumps({'error':{'code':error.code,'message':str(error)}}),file=sys.stderr)
    sys.exit(1)
