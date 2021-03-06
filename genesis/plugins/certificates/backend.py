import ConfigParser
import glob
import OpenSSL
import os

from genesis import apis
from genesis.com import *
from genesis.utils import SystemTime
from genesis.utils.error import SystemTimeError
from genesis.plugins.core.api import ISSLPlugin
from genesis.plugins.webapps.backend import WebappControl


class CertControl(Plugin):
	text = "Certificates"
	iconfont = 'gen-certificate'

	def get_certs(self):
		# Find all certs added by Genesis and return basic information
		certs = []
		if not os.path.exists('/etc/ssl/certs/genesis'):
			os.mkdir('/etc/ssl/certs/genesis')
		if not os.path.exists('/etc/ssl/private/genesis'):
			os.mkdir('/etc/ssl/private/genesis')
		for x in glob.glob('/etc/ssl/certs/genesis/*.gcinfo'):
			cfg = ConfigParser.ConfigParser()
			cfg.read(x)
			certs.append({'name': cfg.get('cert', 'name'),
				'expiry': cfg.get('cert', 'expiry') if cfg.has_option('cert', 'expiry') else 'Unknown',
				'domain': cfg.get('cert', 'domain') if cfg.has_option('cert', 'domain') else 'Unknown',
				'keytype': cfg.get('cert', 'keytype') if cfg.has_option('cert', 'keytype') else 'Unknown',
				'keylength': cfg.get('cert', 'keylength') if cfg.has_option('cert', 'keylength') else 'Unknown',
				'assign': cfg.get('cert', 'assign').split('\n') if cfg.has_option('cert', 'assign') else 'Unknown'})
		return certs

	def get_cas(self):
		# Find all certificate authorities generated by Genesis 
		# and return basic information
		certs = []
		if not os.path.exists('/etc/ssl/certs/genesis/ca'):
			os.mkdir('/etc/ssl/certs/genesis/ca')
		if not os.path.exists('/etc/ssl/private/genesis/ca'):
			os.mkdir('/etc/ssl/private/genesis/ca')
		for x in glob.glob('/etc/ssl/certs/genesis/ca/*.pem'):
			name = os.path.splitext(os.path.split(x)[1])[0]
			cert = OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_PEM, open(x, 'r').read())
			key = OpenSSL.crypto.load_privatekey(OpenSSL.crypto.FILETYPE_PEM, 
				open(os.path.join('/etc/ssl/private/genesis/ca', name+'.key'), 'r').read())
			certs.append({'name': name, 'expiry': cert.get_notAfter()})
		return certs

	def get_ssl_capable(self):
		lst = []
		for x in apis.webapps(self.app).get_sites():
			if x.ssl_able:
				lst.append(x)
		return lst, self.app.grab_plugins(ISSLPlugin)

	def has_expired(self, certname):
		# Return True if the plugin is expired, False if not
		c = open('/etc/ssl/certs/genesis/'+certname+'.crt', 'r').read()
		crt = OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_PEM, c)
		return crt.has_expired()

	def add_ext_cert(self, name, cert, key, chain='', assign=[]):
		# Save the file streams as we get them, and
		# Add a .gcinfo file for a certificate uploaded externally
		try:
			crt = OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_PEM, cert)
		except Exception, e:
			raise Exception('Could not read certificate file. Please make sure you\'ve selected the proper file.', e)
		try:
			ky = OpenSSL.crypto.load_privatekey(OpenSSL.crypto.FILETYPE_PEM, key)
		except Exception, e:
			raise Exception('Could not read private keyfile. Please make sure you\'ve selected the proper file.', e)
		
		x = open(os.path.join('/etc/ssl/certs/genesis', name + '.crt'), 'w')
		x.write(cert)
		if chain:
			x.write('\n') if not cert.endswith('\n') else None
			x.write(chain)
		x.close()
		open(os.path.join('/etc/ssl/private/genesis', name + '.key'), 'w').write(key)

		if ky.type() == OpenSSL.crypto.TYPE_RSA:
			keytype = 'RSA'
		elif ky.type() == OpenSSL.crypto.TYPE_DSA:
			keytype = 'DSA'
		else:
			keytype = 'Unknown'
		cfg = ConfigParser.ConfigParser()
		cfg.add_section('cert')
		cfg.set('cert', 'name', name)
		cfg.set('cert', 'expiry', crt.get_notAfter())
		cfg.set('cert', 'keytype', keytype)
		cfg.set('cert', 'keylength', str(int(ky.bits())))
		cfg.set('cert', 'domain', crt.get_subject().CN)
		cfg.set('cert', 'assign', '\n'.join(assign))
		cfg.write(open(os.path.join('/etc/ssl/certs/genesis', name + '.gcinfo'), 'w'))
		os.chmod(os.path.join('/etc/ssl/certs/genesis', name + '.crt'), 0660)
		os.chmod(os.path.join('/etc/ssl/private/genesis', name + '.key'), 0660)

	def gencert(self, name, vars, hostname):
		# Make sure our folders are in place
		if not os.path.exists('/etc/ssl/certs/genesis'):
			os.mkdir('/etc/ssl/certs/genesis')
		if not os.path.exists('/etc/ssl/private/genesis'):
			os.mkdir('/etc/ssl/private/genesis')

		# If system time is way off, raise an error
		try:
			st = SystemTime().get_offset()
			if st < -3600 or st > 3600:
				raise SystemTimeError(st)
		except:
			raise SystemTimeError('UNKNOWN')

		# Check to see that we have a CA ready
		ca_cert_path = '/etc/ssl/certs/genesis/ca/'+hostname+'.pem'
		ca_key_path = '/etc/ssl/private/genesis/ca/'+hostname+'.key'
		if not os.path.exists(ca_cert_path) and not os.path.exists(ca_key_path):
			self.create_authority(hostname)
		ca_cert = OpenSSL.crypto.load_certificate(OpenSSL.crypto.FILETYPE_PEM, open(ca_cert_path).read())
		ca_key = OpenSSL.crypto.load_privatekey(OpenSSL.crypto.FILETYPE_PEM, open(ca_key_path).read())

		# Generate a key, then use it to sign a new cert
		# We'll use 2048-bit RSA until pyOpenSSL supports ECC
		keytype = OpenSSL.crypto.TYPE_DSA if self.app.get_config(self).keytype == 'DSA' else OpenSSL.crypto.TYPE_RSA
		keylength = int(self.app.get_config(self).keylength)
		try:
			key = OpenSSL.crypto.PKey()
			key.generate_key(keytype, keylength)
			crt = OpenSSL.crypto.X509()
			crt.set_version(3)
			if vars.getvalue('certcountry', ''):
				crt.get_subject().C = vars.getvalue('certcountry')
			if vars.getvalue('certsp', ''):
				crt.get_subject().ST = vars.getvalue('certsp')
			if vars.getvalue('certlocale', ''):
				crt.get_subject().L = vars.getvalue('certlocale')
			if vars.getvalue('certcn', ''):
				crt.get_subject().CN = vars.getvalue('certcn')
			if vars.getvalue('certemail', ''):
				crt.get_subject().emailAddress = vars.getvalue('certemail')
			crt.set_serial_number(int(SystemTime().get_serial_time()))
			crt.gmtime_adj_notBefore(0)
			crt.gmtime_adj_notAfter(2*365*24*60*60)
			crt.set_issuer(ca_cert.get_subject())
			crt.set_pubkey(key)
			crt.sign(key, 'sha1')
		except Exception, e:
			raise Exception('Error generating self-signed certificate: '+str(e))
		open('/etc/ssl/certs/genesis/'+name+'.crt', "wt").write(
			OpenSSL.crypto.dump_certificate(
				OpenSSL.crypto.FILETYPE_PEM, crt)
			)
		os.chmod('/etc/ssl/certs/genesis/'+name+'.crt', 0660)
		open('/etc/ssl/private/genesis/'+name+'.key', "wt").write(
			OpenSSL.crypto.dump_privatekey(
				OpenSSL.crypto.FILETYPE_PEM, key)
			)
		os.chmod('/etc/ssl/private/genesis/'+name+'.key', 0660)

		if key.type() == OpenSSL.crypto.TYPE_RSA:
			keytype = 'RSA'
		elif key.type() == OpenSSL.crypto.TYPE_DSA:
			keytype = 'DSA'
		else:
			keytype = 'Unknown'
		cfg = ConfigParser.ConfigParser()
		cfg.add_section('cert')
		cfg.set('cert', 'name', name)
		cfg.set('cert', 'expiry', crt.get_notAfter())
		cfg.set('cert', 'domain', crt.get_subject().CN)
		cfg.set('cert', 'keytype', keytype)
		cfg.set('cert', 'keylength', str(int(key.bits())))
		cfg.set('cert', 'assign', '')
		cfg.write(open('/etc/ssl/certs/genesis/'+name+'.gcinfo', 'w'))

	def create_authority(self, hostname):
		key = OpenSSL.crypto.PKey()
		key.generate_key(OpenSSL.crypto.TYPE_RSA, 2048)

		ca = OpenSSL.crypto.X509()
		ca.set_version(3)
		ca.set_serial_number(int(SystemTime().get_serial_time()))
		ca.get_subject().CN = hostname
		ca.gmtime_adj_notBefore(0)
		ca.gmtime_adj_notAfter(5*365*24*60*60)
		ca.set_issuer(ca.get_subject())
		ca.set_pubkey(key)
		ca.add_extensions([
		  OpenSSL.crypto.X509Extension("basicConstraints", True,
		                               "CA:TRUE, pathlen:0"),
		  OpenSSL.crypto.X509Extension("keyUsage", True,
		                               "keyCertSign, cRLSign"),
		  OpenSSL.crypto.X509Extension("subjectKeyIdentifier", False, "hash",
		                               subject=ca),
		  ])
		ca.sign(key, 'sha1')
		open('/etc/ssl/certs/genesis/ca/'+hostname+'.pem', "wt").write(
			OpenSSL.crypto.dump_certificate(
				OpenSSL.crypto.FILETYPE_PEM, ca)
			)
		os.chmod('/etc/ssl/certs/genesis/ca/'+hostname+'.pem', 0660)
		open('/etc/ssl/private/genesis/ca/'+hostname+'.key', "wt").write(
			OpenSSL.crypto.dump_privatekey(
				OpenSSL.crypto.FILETYPE_PEM, key)
			)

	def delete_authority(self, data):
		os.unlink(os.path.join('/etc/ssl/certs/genesis/ca', data['name']+'.pem'))
		os.unlink(os.path.join('/etc/ssl/private/genesis/ca', data['name']+'.key'))

	def assign(self, name, assign):
		# Assign a certificate to plugins/webapps as listed
		cfg = ConfigParser.ConfigParser()
		cfg.read('/etc/ssl/certs/genesis/'+name+'.gcinfo')
		alist = cfg.get('cert', 'assign').split('\n')
		for i in alist:
			if i == '':
				alist.remove(i)
		for x in assign:
			if x[0] == 'genesis':
				self.app.gconfig.set('genesis', 'cert_file', 
					'/etc/ssl/certs/genesis/'+name+'.crt')
				self.app.gconfig.set('genesis', 'cert_key', 
					'/etc/ssl/private/genesis/'+name+'.key')
				self.app.gconfig.set('genesis', 'ssl', '1')
				alist.append('Genesis SSL')
				self.app.gconfig.save()
			elif x[0] == 'webapp':
				WebappControl(self.app).ssl_enable(x[1],
					'/etc/ssl/certs/genesis/'+name+'.crt',
					'/etc/ssl/private/genesis/'+name+'.key')
				alist.append(x[1].name + ' ('+x[1].stype+')')
			elif x[0] == 'plugin':
				x[1].enable_ssl()
				alist.append(x[1].text)
		cfg.set('cert', 'assign', '\n'.join(alist))
		cfg.write(open('/etc/ssl/certs/genesis/'+name+'.gcinfo', 'w'))

	def unassign(self, name, assign):
		cfg = ConfigParser.ConfigParser()
		cfg.read('/etc/ssl/certs/genesis/'+name+'.gcinfo')
		alist = cfg.get('cert', 'assign').split('\n')
		for i in alist:
			if i == '':
				alist.remove(i)
		for x in assign:
			if x[0] == 'genesis':
				self.app.gconfig.set('genesis', 'cert_file', '')
				self.app.gconfig.set('genesis', 'cert_key', '')
				self.app.gconfig.set('genesis', 'ssl', '0')
				alist.remove('Genesis SSL')
				self.app.gconfig.save()
			elif x[0] == 'webapp':
				WebappControl(self.app).ssl_disable(x[1])
				alist.remove(x[1].name + ' ('+x[1].stype+')')
			elif x[0] == 'plugin':
				x[1].disable_ssl()
				alist.remove(x[1].text)
		cfg.set('cert', 'assign', '\n'.join(alist))
		cfg.write(open('/etc/ssl/certs/genesis/'+name+'.gcinfo', 'w'))

	def remove_notify(self, name):
		# Called by plugin when removed.
		# Removes the associated entry from gcinfo tracker file
		try:
			cfg = ConfigParser.ConfigParser()
			cfg.read('/etc/ssl/certs/genesis/'+name+'.gcinfo')
			alist = []
			for x in cfg.get('cert', 'assign').split('\n'):
				if x != name:
					alist.append(x)
			cfg.set('cert', 'assign', '\n'.join(alist))
			cfg.write(open('/etc/ssl/certs/genesis/'+name+'.gcinfo', 'w'))
		except:
			pass

	def remove(self, name):
		# Remove cert, key and control file for associated name
		cfg = ConfigParser.ConfigParser()
		cfg.read('/etc/ssl/certs/genesis/'+name+'.gcinfo')
		alist = cfg.get('cert', 'assign').split('\n')
		wal, pal = self.get_ssl_capable()
		for x in wal:
			if (x.name+' ('+x.stype+')') in alist:
				WebappControl(self.app).ssl_disable(x)
		for y in pal:
			if y.text in alist:
				y.disable_ssl()
		if 'Genesis SSL' in alist:
			self.app.gconfig.set('genesis', 'cert_file', '')
			self.app.gconfig.set('genesis', 'cert_key', '')
			self.app.gconfig.set('genesis', 'ssl', '0')
			self.app.gconfig.save()
		os.unlink('/etc/ssl/certs/genesis/'+name+'.gcinfo')
		try:
			os.unlink('/etc/ssl/certs/genesis/'+name+'.crt')
		except:
			pass
		try:
			os.unlink('/etc/ssl/private/genesis/'+name+'.key')
		except:
			pass
