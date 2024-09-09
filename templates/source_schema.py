{
'proj': {
        'required': True,
        'type': 'dict',
        'schema': {
            'file': {
                'required': True,
                'type': 'string'
                    },
    },
    'data': {
        'required': True,
        'type': 'dict',
        'schema': {
            'manufacturer': {
                'required': True,
                'type': 'string'
                    },            
            'file': {
                'required': True,
                'type': 'string'
                    },
    }},
    'tags': {
        'required': True,
        'type': 'dict',
        'schema': {
            'manufacturer': {
                'required': True,
                'type': 'string'
                    },            
            'file': {
                'required': True,
                'type': 'string'
                    },
                  }
    }
}
}