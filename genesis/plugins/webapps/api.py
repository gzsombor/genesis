from genesis.com import *
from genesis import apis

import ConfigParser
import glob
import nginx
import os
import re


class Webapp(object):
    name = ''
    stype = ''
    ssl = False
    ssl_able = True
    addr = ''
    port = ''
    path = ''
    php = False
    sclass = None
    enabled = False


class Webapps(apis.API):
    def __init__(self, app):
        self.app = app

    class IWebapp(Interface):
        def pre_install(self, name, vars):
            pass

        def post_install(self, name, path, vars):
            pass

        def pre_remove(self, name, path):
            pass

        def post_remove(self, name):
            pass

        def ssl_enable(self, path, cfile, kfile):
            pass

        def ssl_disable(self, path):
            pass

    def get_apptypes(self):
        applist = []
        for plugin in self.app.grab_plugins(apis.webapps.IWebapp):
            applist.append(plugin)
        return applist

    def get_sites(self):
        applist = []
        if not os.path.exists('/etc/nginx/sites-available'):
            os.makedirs('/etc/nginx/sites-available')
        if not os.path.exists('/etc/nginx/sites-enabled'):
            os.makedirs('/etc/nginx/sites-enabled')

        for site in os.listdir('/etc/nginx/sites-available'):
            w = Webapp()
            # Set default values and regexs to use
            w.name = site
            w.addr = False
            w.port = '80'
            w.stype = 'Unknown'
            w.path = os.path.join('/etc/nginx/sites-available', site)
            rtype = re.compile('GENESIS ((?:[a-z][a-z]+))', flags=re.IGNORECASE)
            rport = re.compile('(\\d+)\s*(.*)')

            # Get actual values
            try:
                c = nginx.loadf(w.path)
                w.stype = re.match(rtype, c.filter('Comment')[0].comment).group(1)
                w.port, w.ssl = re.match(rport, c.servers[0].filter('Key', 'listen')[0].value).group(1, 2)
                w.addr = c.servers[0].filter('Key', 'server_name')[0].value
                w.path = c.servers[0].filter('Key', 'root')[0].value
                w.php = True if 'php' in c.servers[0].filter('Key', 'index')[0].value else False
            except IndexError:
                pass

            w.enabled = True if os.path.exists(os.path.join('/etc/nginx/sites-enabled', site)) else False

            w.sclass = self.get_interface(w.stype)
            w.sinfo = self.get_info(w.stype)
            w.dbengine = w.sinfo.dbengine
            w.ssl_able = w.sinfo.ssl if hasattr(w.sinfo, 'ssl') else False

            applist.append(w)
        return applist

    def get_info(self, name):
        return filter(lambda x: x.__class__.__name__ == name,
            self.app.grab_plugins(apis.webapps.IWebapp))[0].plugin_info

    def get_interface(self, name):
        return filter(lambda x: x.__class__.__name__ == name,
            self.app.grab_plugins(apis.webapps.IWebapp))[0]

    def cert_remove_notify(self, name, stype):
        # Called by webapp when removed.
        # Removes the associated entry from gcinfo tracker file
        # Placed here for now to avoid awkward circular import
        try:
            cfg = ConfigParser.ConfigParser()
            for x in glob.glob('/etc/ssl/certs/genesis/*.gcinfo'):
                cfg.read(x)
                alist = []
                write = False
                for i in cfg.get('cert', 'assign').split('\n'):
                    if i != (name+' ('+stype+')'):
                        alist.append(i)
                    else:
                        write = True
                if write == True:
                    cfg.set('cert', 'assign', '\n'.join(alist))
                    cfg.write(open(x, 'w'))
        except:
            pass
