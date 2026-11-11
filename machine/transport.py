"""Credential-bearing requests never follow redirects to another destination."""
from urllib.request import HTTPRedirectHandler, build_opener
from urllib.error import HTTPError


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,req,fp,code,msg,headers,newurl):
        raise HTTPError(req.full_url,code,"Redirect refused for authenticated request",headers,fp)


def open_authenticated(request,timeout=30):
    return build_opener(NoRedirect()).open(request,timeout=timeout)
