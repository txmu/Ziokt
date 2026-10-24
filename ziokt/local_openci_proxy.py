"""Bounded same-node OpenCI mount; no caller-selected upstream or credentials."""
import http.client
import ipaddress
from urllib.parse import urlsplit


class LocalOpenCI:
    def __init__(self,endpoint):
        value=urlsplit(endpoint)
        if (value.scheme!='http' or value.username or value.password or value.path not in {'','/'} or value.query or value.fragment or not value.hostname or not ipaddress.ip_address(value.hostname).is_loopback or not value.port):raise ValueError('explicit loopback Controller endpoint required')
        self.host,self.port,self.authority=value.hostname,value.port,value.netloc

    def forward(self,handler):
        route=handler.path[len('/openci'):];parsed=urlsplit(route)
        if parsed.scheme or parsed.netloc or parsed.fragment or not parsed.path.startswith('/') or handler.command not in {'GET','POST','PUT'}:raise ValueError('bounded Controller route required')
        if handler.headers.get('Transfer-Encoding') is not None:raise ValueError('encoded proxy body rejected')
        if len(handler.headers.get_all('Content-Length',[]))>1:raise ValueError('duplicate message length rejected')
        length=handler.headers.get('Content-Length','0')
        if not length.isdigit() or int(length)>1048576 or handler.command=='GET' and int(length):raise ValueError('bounded Controller message required')
        body=handler.rfile.read(int(length))
        if len(body)!=int(length):raise ValueError('truncated Controller message')
        headers={'Host':self.authority,'Connection':'close'}
        for name in ('Authorization','Content-Type','Origin'):
            values=handler.headers.get_all(name,[])
            if len(values)>1:raise ValueError('duplicate forwarding authority header')
            if values:headers[name]=values[0]
        connection=http.client.HTTPConnection(self.host,self.port,timeout=30)
        try:
            connection.request(handler.command,route,body=body if handler.command!='GET' else None,headers=headers)
            response=connection.getresponse();data=response.read(8*1024*1024+1)
            if len(data)>8*1024*1024 or 300<=response.status<400:raise ValueError('Controller response budget or redirect rejected')
            handler.send_response_only(response.status)
            for name,value in response.getheaders():
                if name.lower() in {'content-type','content-security-policy','x-content-type-options','referrer-policy','permissions-policy','cache-control'}:handler.send_header(name,value)
            handler.send_header('Content-Length',str(len(data)));handler.send_header('Connection','close');handler.end_headers();handler.wfile.write(data)
        finally:connection.close()
