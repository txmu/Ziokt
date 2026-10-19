"""Real Firefox WebExtension smoke test; Selenium and Firefox are CI dependencies."""
import json,os,secrets,tempfile,threading,zipfile
from pathlib import Path
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as expected
from ziokt.content_fabric import Fabric
from ziokt.content_server import server


def main():
 with tempfile.TemporaryDirectory() as temp:
  root=Path(temp);fabric=Fabric(root/'state');fabric.create_group('alice','books.open');token=secrets.token_hex(32)
  http=server(fabric,{'port':0,'allow_webextensions':True,'tokens':[{'account':'alice','token':token,'scopes':['applications:read','netnews:read','netnews:write']}]});thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start();origin='http://127.0.0.1:'+str(http.server_port)
  extension=Path('dist/extensions/firefox');manifest=json.loads((extension/'manifest.json').read_text());manifest['host_permissions']=[origin+'/*'];addon=root/'extension.xpi'
  with zipfile.ZipFile(addon,'w') as archive:
   archive.writestr('manifest.json',json.dumps(manifest))
   for file in extension.rglob('*'):
    if file.is_file() and file.name!='manifest.json':archive.write(file,str(file.relative_to(extension)))
  options=webdriver.FirefoxOptions();options.add_argument('-headless')
  if os.environ.get('ZIOKT_FIREFOX_BINARY'):options.binary_location=os.environ['ZIOKT_FIREFOX_BINARY']
  uuid='f3f6b5c1-1430-4cf3-b385-8318a9d9d236';options.set_preference('extensions.webextensions.uuids',json.dumps({'companion@ziokt.local':uuid}));options.set_preference('intl.accept_languages','en-US,en')
  driver=None
  try:
   driver=webdriver.Firefox(options=options);driver.install_addon(str(addon),temporary=True);driver.get('moz-extension://'+uuid+'/popup.html');wait=WebDriverWait(driver,20)
   driver.find_element(By.NAME,'endpoint').clear();driver.find_element(By.NAME,'endpoint').send_keys(origin);driver.find_element(By.NAME,'token').send_keys(token);driver.find_element(By.CSS_SELECTOR,'#connect button').click();wait.until(expected.text_to_be_present_in_element((By.ID,'status'),'Connected.'))
   driver.find_element(By.ID,'groups').click();wait.until(expected.element_to_be_clickable((By.XPATH,"//button[text()='books.open']"))).click();driver.find_element(By.CSS_SELECTOR,'#post input[name=subject]').send_keys('Firefox article');driver.find_element(By.CSS_SELECTOR,'#post textarea').send_keys('Actual Firefox WebExtension post');driver.find_element(By.CSS_SELECTOR,'#post button').click();wait.until(expected.text_to_be_present_in_element((By.ID,'status'),'Article durably published'))
   assert fabric.articles('alice','books.open')['items'][0]['subject']=='Firefox article'
   print(json.dumps({'browser':'firefox','real_extension':True,'real_node':True,'post':True,'host_permission_prompt':'pregranted for automation; manual prompt not tested','status':'passed'}))
  finally:
   if driver:driver.quit()
   http.shutdown();http.server_close();thread.join();fabric.close()


if __name__=='__main__':main()
