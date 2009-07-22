import urllib
import re
import cPickle
import os
import subprocess
import tempfile

import logging

from dirac.lib.base import *
from dirac.lib.diset import getRPCClient
import dirac.lib.credentials as credentials # getUserDN() getUsername()
import DIRAC
from DIRAC import S_ERROR,S_OK, gConfig
from DIRAC.ConfigurationSystem.Client import PathFinder

from DIRAC.Core.Workflow.Workflow import Workflow,fromXMLString


log = logging.getLogger(__name__)

class PrTpl(object):
  """ Production Template engine
  AZ: I know it is not the best :)
  It undestand: {{<sep><ParName>[#<Label>]}}
  Where:
    <sep> - not alpha character to be inserted
            before parameter value in case it
            is not empty
    <ParName> - parameter name (must begin
            with alpha character) to substitute
    <Label> - if '#' is found after '{{', everything after
            it till '}}' is Label for the parameter
            (default to ParName) In case you use one parameter
            several times, you can specify the label only once.
  """
  __par_re  = "\{\{(\W)?([^\}#]+)#?([^\}]*)\}\}"
  __par_sub = "\{\{(\W|)?%s[^\}]*\}\}"
  def __init__(self,tpl_xml):
    self.tpl = tpl_xml
    self.pdict = {}
    for x in re.findall(self.__par_re,self.tpl):
      if x[1] in self.pdict and not x[2]:
        continue
      label = x[2]
      if not label:
        label = x[1]
      self.pdict[x[1]] = label

  def getParams(self):
    """ Return the dictionary with parameters (value is label) """
    return self.pdict

  def apply(self,pdict):
    """ Return template with substituted values from pdict """
    result = self.tpl
    for p in self.pdict:
      value = str(pdict.get(p,''))
      if value:
        value = "\\g<1>" + value
      result = re.sub(self.__par_sub % p, value, result)
    return result

softBaseURL = 'http://lhcbproject.web.cern.ch/lhcbproject/dist/'

def getSoftVersions(name, web_names='',add=''):
  """ Return list of all downloadable versions
      of specified software package.
      web_name is default to name_name
      add specify verbatim version to add to the list
  """
  if web_names == '':
    web_names = name + '_' + name
# Download the page
  url = softBaseURL+name+'/'
  try:
    f = urllib.urlopen(url)
    page = f.read()
    f.close()
  except Exception, e:
    return S_ERROR("Can't download %s: %s"%(url,str(e)))
  uver = {}
  for web_name in web_names.split(','):
    # Find all references to package
    ver = re.compile(web_name+'_([^_]+)\\.tar\\.gz').findall(page)
    # Remove duplicates
    for x in ver:
      uver[x] = 1
  for v in add.split(','):
    if(v):
      uver[v] = 1
  ver = uver.keys()
# Sort the result
  ver.sort()
# Newer first
  ver.reverse()
  return S_OK(ver)

def bkProductionProgress(id):
  RPC = getRPCClient('Bookkeeping/BookkeepingManager')
  result = RPC.getProductionInformations(id)
  if not result['OK']:
    return result
  info = result['Value']
  if not 'Number of events' in info:
    return S_OK(0)
  allevents = info['Number of events']
  if len(allevents) == 0:
    return S_OK(0)
  if len(allevents) > 1:
    return S_ERROR('More than one output file type. Unsupported.')
  return S_OK(allevents[0][1])

def SelectAndSort(rows,default_sort):
  total = len(rows)
  if total == 0:
    return { 'OK':True, 'result':{}, 'total': 0 }
  try:
    start = int(request.params.get('start', 0))
    limit = int(request.params.get('limit', total))
    sort  = request.params.get('sort', default_sort)
    dir   = request.params.get('dir', 'ASC')
    if not sort in rows[0]:
      raise Exception('Sort field '+sort+' is not found')
  except Exception, e:
    return S_ERROR('Badly formatted list request: '+str(e))
  rows.sort(key=lambda x: x[sort], reverse=(dir!='ASC'))
  return { 'OK':True, 'result':rows[start:start+limit], 'total': total }



# DIRAC services based
class RealRequestEngine:
  serviceFields = [ 'RequestID', 'HasSubrequest', 'ParentID', 'MasterID',
                    'RequestName', 'RequestType', 'RequestState',
                    'RequestPriority', 'RequestAuthor', 'RequestPDG',
                    'SimCondition', 'SimCondID',
                    'ProPath', 'ProID',
                    'EventType', 'NumberOfEvents', 'Comments', 'Description',
                    'bk','bkTotal','rqTotal','crTime','upTime' ]
  
  localFields  = [ 'ID', '_is_leaf', '_parent', '_master',
                   'reqName', 'reqType', 'reqState',
                   'reqPrio', 'reqAuthor', 'reqPDG',
                   'simDesc', 'simCondID',
                   'pDsc', 'pID',
                   'eventType', 'eventNumber', 'reqComment', 'reqDesc',
                   'eventBK','eventBKTotal','EventNumberTotal',
                   'creationTime', 'lastUpdateTime' ]

  simcondFields = [ 'Generator', 'MagneticField', 'BeamEnergy',
                    'Luminosity', 'DetectorCond', 'BeamCond',
                    'configName', 'configVersion', 'condType',
                    'inProPass', 'inFileType', 'inProductionID',
                    'inDataQualityFlag' ]

  def getRequestFields(self):
    result = dict.fromkeys(self.localFields,None)
    result.update(dict.fromkeys(self.simcondFields))
    for x in ['App','Ver','Opt','DDDb','CDb','EP']:
      for i in range(1,8):
        result['p%d%s' % (i,x)] = None
    result['userName'] = credentials.getUsername()
    result['userDN'] = credentials.getUserDN()
    return result
    
  def __2local(self,req):
    result = {}
    for x,y in zip(self.localFields,self.serviceFields):
      result[x] = req[y]
    result['_is_leaf'] = not result['_is_leaf']
    if req['bkTotal']!=None and req['rqTotal']!=None and req['rqTotal']:
      result['progress']=long(req['bkTotal'])*100/long(req['rqTotal'])
    else:
      result['progress']=None
    if req['SimCondDetail']:
      result.update(cPickle.loads(req['SimCondDetail']))
    if req['ProDetail']:
      result.update(cPickle.loads(req['ProDetail']))
    result['creationTime'] = str(result['creationTime'])
    result['lastUpdateTime'] = str(result['lastUpdateTime'])
    for x in result:
      if x != '_parent' and result[x] == None:
        result[x] = ''
    return result;

  def __fromlocal(self,req):
    result = {}
    for x,y in zip(self.localFields[2:-5],self.serviceFields[2:-5]):
      if x in req:
        result[y] = req[x]

    SimCondDetail = {}
    for x in self.simcondFields:
      if x in req and str(req[x])!='':
        SimCondDetail[x]=req[x]
    if len(SimCondDetail):
      result['SimCondDetail'] = cPickle.dumps(SimCondDetail)

    ProDetail = {}  
    for x in req:
      if str(x)[0] == 'p':
        if str(req[x])!='':
          ProDetail[x]=req[x]
    if len(ProDetail):
      result['ProDetail'] = cPickle.dumps(ProDetail)

    return result

  def getProductionRequest(self,ids):
    RPC = getRPCClient( "ProductionManagement/ProductionRequest" )
    result = RPC.getProductionRequest(ids);
    if not result['OK']:
      return result
    rr = result['Value']
    lr = {}
    for x in rr:
      lr[x] = self.__2local(rr[x])
    return S_OK(lr)

  def getProductionRequestList(self,parent):
    try:
      offset    = long(request.params.get('start', 0))
      limit     = long(request.params.get('limit', 0))
      sortBy    = str(request.params.get('sort', 'ID'))
      sortBy    = self.serviceFields[self.localFields.index(sortBy)]
      sortOrder = str(request.params.get('dir', 'ASC'))
    except Exception, e:
      return S_ERROR('Badly formatted list request: '+str(e))
    RPC = getRPCClient( "ProductionManagement/ProductionRequest" )
    result = RPC.getProductionRequestList(parent,sortBy,sortOrder,
                                          offset,limit);
    if not result['OK']:
      return result
    rows = [self.__2local(x) for x in result['Value']['Rows']]
    return { 'OK':True, 'result':rows, 'total': result['Value']['Total'] }

  def updateProductionRequest(self,id,rdict):
    RPC = getRPCClient( "ProductionManagement/ProductionRequest" )
    req = self.__fromlocal(rdict)
    result = RPC.updateProductionRequest(id,req);
    return result

  def createProductionRequest(self,rdict):
    RPC = getRPCClient( "ProductionManagement/ProductionRequest" )

    rdict['RequestAuthor'] = credentials.getUsername()
    req = self.__fromlocal(rdict)

    result = RPC.createProductionRequest(req);
    return result

  def deleteProductionRequest(self,id):
    RPC = getRPCClient( "ProductionManagement/ProductionRequest" )
    result = RPC.deleteProductionRequest(id)
    return result

  def duplicateProductionRequest(self,id):
    RPC = getRPCClient( "ProductionManagement/ProductionRequest" )
    return RPC.duplicateProductionRequest(id)

  def reset(self):
    return S_ERROR('You must be joking...')

  def getProductionProgressList(self,requestID):
    RPC = getRPCClient( "ProductionManagement/ProductionRequest" )
    result = RPC.getProductionProgressList(requestID)
    if not result['OK']:
      return result
    return { 'OK':True, 'result':result['Value']['Rows'],
             'total': result['Value']['Total'] }

  def addProduction(self,pdict):
    RPC = getRPCClient( "ProductionManagement/ProductionRequest" )
    return RPC.addProductionToRequest(pdict)

  def removeProduction(self,productionID):
    RPC = getRPCClient( "ProductionManagement/ProductionRequest" )
    return RPC.removeProductionFromRequest(productionID)

  def useProduction(self,productionID,used):
    RPC = getRPCClient( "ProductionManagement/ProductionRequest" )
    return RPC.useProductionForRequest(productionID,used)

  def getRequestHistory(self,requestID):
    RPC = getRPCClient( "ProductionManagement/ProductionRequest" )
    result = RPC.getRequestHistory(requestID)
    if not result['OK']:
      return result
    rows = result['Value']['Rows']
    for row in rows:
      row['TimeStamp'] = str(row['TimeStamp'])
    return { 'OK':True, 'result':rows,'total': result['Value']['Total'] }

  def getTemplate(self,name):
    RPC = getRPCClient( "ProductionManagement/ProductionRequest" )
    return RPC.getProductionTemplate(str(name))
    #RPC = getRPCClient("ProductionManagement/ProductionManager")
    #return RPC.getWorkflow(str(name))

  def __cnFromCred(self,cred):
    for field in cred.split('/'):
      if field.startswith('CN='):
        return field[3:]
    return cred
    
  def __beautifyWfList(self,wflist):
    """ Make the content user friendly (if possible)
    Extract CN from credential and use it as user name
    """
    result = []
    for wf in wflist:
      wf['Author'] = self.__cnFromCred(wf['AuthorDN'])+'@'+wf['AuthorGroup']
      result.append( wf )
    return result

  def templates(self):
    RPC = getRPCClient( "ProductionManagement/ProductionRequest" )
    ret = RPC.getProductionTemplateList()
    if not ret['OK']:
      return ret
    dvalue = {} # Remove "_run.py" templates from the list
    for x in ret['Value']:
      dvalue[x['WFName']] = x
    value = []
    for x in dvalue:
      master = x.replace('_run.py','')
      if  master != x and master in dvalue:
        continue
      value.append(dvalue[x])
    return { 'OK':True, 'total': len(value), 'result': value }

    #RPC = getRPCClient("ProductionManagement/ProductionManager")
    #result = RPC.getListWorkflows()
    #if not result['OK']:
    #  return result
    #wflist = self.__beautifyWfList(result['Value'])
    #templates = []
    #for x in wflist:
    #  if x['WFParent'] == 'production/template':
    #    templates.append(x)
    #return { 'OK':True, 'total': len(wflist), 'result': templates }


# Session based
class FakeRequestEngine:
  def __init__(self):
    if 'fake_request_db' in session:
      return
    session['fake_request_db'] = {}
    session['fake_request_id'] = 0
    session.save()

  def reset(self):
    session['fake_request_db'] = {}
    session['fake_request_id'] = 0
    session.save()
    return S_OK('Reset done')

  def getProductionRequest(self,ids):
    all = session['fake_request_db']
    result = {}
    for x in ids:
      if x in all:
        result[x] = all[x]
    return {'OK': True, 'Value': result}

  def getProductionRequestList(self,parent):
    all = session['fake_request_db']
    rows = []
    if not parent:
      for id in all:
        if not all[id]['_master']:
          rows.append(all[id])
    else:
      for id in all:
        if all[id]['_parent'] == parent:
          rows.append(all[id])
    return SelectAndSort(rows,'ID')
  
  def updateProductionRequest(self,id,rdict):
    fdb = session['fake_request_db']
    try:
      iid = long(id)
      if not iid in fdb:
        return S_ERROR('Specified Request does not exist');
      rdict['_is_leaf'] = fdb[iid]['_is_leaf']
      rdict['_parent']  = fdb[iid]['_parent']
      rdict['_master']  = fdb[iid]['_master']
      rdict['ID'] = iid
      fdb[iid] = rdict
    except Exception,e:
      return S_ERROR(e)
    session.save()
    return S_OK(id)
  
  def createProductionRequest(self,rdict):
    fdb = session['fake_request_db']
    if '_parent' in rdict and rdict['_parent']:
      try:
        iparent = long(rdict['_parent'])
      except Exception,e:
        return S_ERROR(e)
      if not iparent in fdb:
        return S_ERROR('Parent request does not exit')
      if not '_master' in rdict:
        if fdb[iparent]['_master']:
          return S_ERROR('Can not substructure subrequest')
      rdict['_parent'] = iparent
    else:
      rdict['_parent'] = None
    if not '_master' in rdict or not rdict['_master']:
      rdict['_master'] = None
    else:
      if not rdict['_parent']:
        return S_ERROR('Master specified without parent')
      try:
        imaster = long(rdict['_master'])
      except Exception,e:
        return S_ERROR('Master ID is not a number')
      if not imaster in fdb:
        return S_ERROR('Master request does not exit')
      rdict['_master'] = imaster
      while iparent and iparent != imaster:
        iparent = fdb[iparent]['_parent']
      if not iparent:
        S_ERROR('Master is not in parent tree')
    if rdict['_parent']:
      if fdb[rdict['_parent']]['_is_leaf']:
        fdb[rdict['_parent']]['_is_leaf'] = False
    id = int(session['fake_request_id'])
    id +=1;
    rdict['_is_leaf'] = True
    rdict['ID'] = id
    session['fake_request_db'][id] = rdict
    session['fake_request_id'] = id
    session.save();
    return S_OK(id);

  def _modifySubStructure(self,fdb,iid):
    todelete = []
    for i in fdb.keys():
      if fdb[i]['_master'] == iid:
        todelete.append(i)
    for i in todelete:
      del fdb[i]
    for i in fdb.keys():
      if fdb[i]['_parent'] == iid:
        fdb[i]['_parent'] = fdb[iid]['_parent']
  
  def deleteProductionRequest(self,id):
    fdb = session['fake_request_db']
    try:
      iid = long(id)
      if not iid in fdb:
        return S_ERROR('Specified Request does not exist');
      self._modifySubStructure(fdb,iid)
      iparent = fdb[iid]['_parent']
      del fdb[iid]
      if iparent:
        is_leaf = True
        for i in fdb.keys():
          if fdb[i]['_parent'] == iparent:
            is_leaf = False
            break
        fdb[iparent]['_is_leaf'] = is_leaf
    except Exception,e:
      return S_ERROR(e);
    session.save();
    return S_OK(id);

  def duplicateProductionRequest(self,id):
    return S_ERROR('Not implemented')
  
  def getProductionProgressList(self,requestID):
    return S_ERROR('Not implemented')

  def addProduction(self,pdict):
    return S_ERROR('Not implemented')

  def removeProduction(self,productionID):
    return S_ERROR('Not implemented')

  def useProduction(self,productionID,used):
    return S_ERROR('Not implemented')

  def getRequestHistory(self,requestID):
    return S_ERROR('Not implemented')
    
class ProductionrequestController(BaseController):

  def __init__(self):
    BaseController.__init__(self)
    self.engine = RealRequestEngine()
#    self.engine = FakeRequestEngine()

  def index(self):
    return redirect_to(action='display')
    
  def display(self):
    return render("production/ProductionRequest.mako")

  @jsonify
  def list(self):
    anode = request.params.get('anode',0)
    try:
      anode = long(anode)
    except Exception,e:
      return S_ERROR('anode is not a number')
    return self.engine.getProductionRequestList(anode);

  @jsonify
  def save(self):
    rdict = dict(request.params)
    if 'ID' in rdict:
      try:
        id = long(rdict['ID']);
      except Exception, e:
        return S_ERROR('Reqiest ID is not a number')
      del rdict['ID'];
      return self.engine.updateProductionRequest(id,rdict)
    return self.engine.createProductionRequest(rdict);

  @jsonify
  def delete(self):
    id  = str(request.params.get('ID', ''))
    try:
      id = long(id);
    except Exception, e:
      return S_ERROR('Reqiest ID is not a number')
    return self.engine.deleteProductionRequest(id);

  @jsonify
  def duplicate(self):
    id  = str(request.params.get('ID', ''))
    try:
      id = long(id);
    except Exception, e:
      return S_ERROR('Reqiest ID is not a number')
    return self.engine.duplicateProductionRequest(id);

  @jsonify
  def reset(self):
    return self.engine.reset()

  @jsonify
  def bkk_configs(self):
    RPC = getRPCClient('Bookkeeping/BookkeepingManager')
    return RPC.getAvailableConfigurations();

  @jsonify
  def bkk_tree(self):
    configName    = str(request.params.get('configName', ''))
    configVersion = str(request.params.get('configVersion', ''))

    RPC = getRPCClient('Bookkeeping/BookkeepingManager')
    value = []
    if not configName:
      result = RPC.getAvailableConfigurations();
      if not result['OK']:
        return result
      if not configName:
        known = {}
        for pair in result['Value']:
          name = pair[0]
          if not name in known:
            value.append({
              'id':         '/'+name,
              'text':       name,
              'configName': name
              })
            known[name] = True
      return {'OK': True, 'Value': value}
    if not configVersion:
      result = RPC.getAvailableConfigurations();
      if not result['OK']:
        return result
      for pair in result['Value']:
        name = pair[0]
        if name == configName:
          version = pair[1]
          value.append({
            'id':     '/'+name+'/'+version,
            'text':   version,
            'configName': name,
            'configVersion': version,
            })
      return {'OK': True, 'Value': value}
    if True:
      result = RPC.getSimulationConditions(configName,configVersion,0);
      if not result['OK']:
        return result
      for cond in result['Value']:
        value.append({
          'id':     '/'+configName+'/'+configVersion+'/'+str(cond[0]),
          'text':   cond[1],
          'configName': configName,
          'configVersion': configVersion,
          'simCondID': cond[0],
          'simDesc': cond[1],
          'BeamCond': cond[2],
          'BeamEnergy': cond[3],
          'Generator': cond[4],
          'MagneticField': cond[5],
          'DetectorCond': cond[6],
          'Luminosity': cond[7],
          'leaf': True
          })
      return {'OK': True, 'Value': value}

    return {'OK': False, 'Message': 'Not implemented'}

  bkSimCondFields = [ 'simCondID', 'simDesc', 'BeamCond',
                      'BeamEnergy', 'Generator',
                      'MagneticField', 'DetectorCond',
                      'Luminosity' ]
  bkRunCondFields = [ 'simCondID', 'simDesc', 'BeamCond',
                      'BeamEnergy', 'MagneticField',
                      'detVELO', 'detIT', 'detTT', 'detOT',
                      'detRICH1', 'detRICH2', 'detSPD_PRS',
                      'detECAL', 'detHCAL', 'detMUON',
                      'detL0','detHLT' ]

  def __runDetectorCond(self,cond):
    incl = []
    not_incl = []
    unknown = []
    for x in self.bkRunCondFields[5:]:
      if not x in cond:
        unknown.append(x[3:])
      elif cond[x] == 'INCLUDED':
        incl.append(x[3:])
      elif cond[x] == 'NOT INCLUDED':
        not_incl.append(x[3:])
      else:
        unknown.append(x[3:])
    if len(incl) > len(not_incl):
      if not len(not_incl):
        s = "all"
        if len(unknown):
          s += " except unknown %s" % ','.join(unknown)
      else:
        s = "without %s" % ','.join(not_incl)
        if len(unknown):
          s += " and unknown %s" % ','.join(unknown)
    else:
      if len(incl):
        s = "only %s" % ','.join(incl)
        if len(unknown):
          s += " and unknown %s" % ','.join(unknown)
      else:
        s = "no"
        if len(unknown):
          s += " with unknown %s" % ','.join(unknown)
    return s

  def __findSimCond(self,RPC,configName,configVersion,condType,simCondID):
    if simCondID == 'ALL':
      if condType == 'Run':
        d = dict.fromkeys(self.bkRunCondFields,'')
        d['condType'] = 'Run'
        d['Generator'] = ''
        d['DetectorCond'] = ''
        d['Luminosity'] = ''
      else:
        d = dict.fromkeys(self.bkSimCondFields,'')
        d['condType'] = 'Simulation'
      d['simCondID'] = '999999'
      d['simDesc'] = 'ALL'
      return S_OK(d)
    if condType == 'Run':
      result = RPC.getSimulationConditions(configName,configVersion,1)
    else:
      result = RPC.getSimulationConditions(configName,configVersion,0)
    if not result['OK']:
      return result
    for cond in result['Value']:
      if str(cond[0]) != str(simCondID):
        continue
      if condType == 'Run':
        d = dict(zip(self.bkRunCondFields,cond))
        d['DetectorCond'] = self.__runDetectorCond(d)
      else:
        d = dict(zip(self.bkSimCondFields,cond))
      d['condType'] = condType
      d['simCondID'] = simCondID
      return S_OK(d)
    return S_ERROR("Conditions %s is not found" % str(simCondID))

  @jsonify
  def bkk_input_prod(self):
    configName    = str(request.params.get('configName', ''))
    configVersion = str(request.params.get('configVersion', ''))
    simCondID     = str(request.params.get('simCondID', ''))
    inProPass     = str(request.params.get('inProPass', ''))
    eventType        = str(request.params.get('eventType', ''))

    if simCondID == '999999':
      simCondID = 'ALL'

    RPC = getRPCClient('Bookkeeping/BookkeepingManager')
    result = RPC.getProductionsWithSimcond(configName,configVersion,
                                           simCondID,inProPass,eventType)
    if not result['OK']:
      return result
    value = []
    if len(result['Value']):
      value.append({'id':0,'text':'ALL'})
    for x in result['Value']:
      prod = x[0]
      if prod < 0:
        prod = -prod;
      value.append({ 'id': prod, 'text': prod});
    return { 'OK': True, 'total': len(value), 'result': value }

  @jsonify
  def bkk_dq_list(self):
    RPC = getRPCClient('Bookkeeping/BookkeepingManager')
    result = RPC.getAvailableDataQuality()
    if not result['OK']:
      return result
    value = []
    if len(result['Value']):
      value.append({'v':'ALL'})
    for x in result['Value']:
      value.append({ 'v': x});
    return { 'OK': True, 'total': len(value), 'result': value }

  @jsonify
  def bkk_input_tree(self):
    configName    = str(request.params.get('configName', ''))
    configVersion = str(request.params.get('configVersion', ''))
    simCondID     = str(request.params.get('simCondID', ''))
    condType      = str(request.params.get('condType', ''))
    inProPass     = str(request.params.get('inProPass', ''))
    evType        = str(request.params.get('evType', ''))

    if simCondID == '999999':
      simCondID = 'ALL'

    RPC = getRPCClient('Bookkeeping/BookkeepingManager')
    value = []
    if not configName:
      result = RPC.getAvailableConfigurations();
      if not result['OK']:
        return result
      if not configName:
        known = {}
        for pair in result['Value']:
          name = pair[0]
          if not name in known:
            value.append({
              'id':         '/'+name,
              'text':       name,
              'configName': name
              })
            known[name] = True
      return {'OK': True, 'Value': value}
    if not configVersion:
      result = RPC.getAvailableConfigurations();
      if not result['OK']:
        return result
      for pair in result['Value']:
        name = pair[0]
        if name == configName:
          version = pair[1]
          value.append({
            'id':     '/'+name+'/'+version,
            'text':   version,
            'configName': name,
            'configVersion': version,
            })
      return {'OK': True, 'Value': value}
    if not simCondID or not condType:
      result = RPC.getSimulationConditions(configName,configVersion,0);
      if len(result['Value']):
        for cond in result['Value']:
          d = { 'id':     '/'+configName+'/'+configVersion+'/'+str(cond[0]),
                'text':   cond[1], 'leaf': False, 'condType': 'Simulation',
                'configName': configName, 'configVersion': configVersion }
          d.update(dict(zip(self.bkSimCondFields,cond)))
          value.append(d)
        if len(value):
          d = { 'id':     '/'+configName+'/'+configVersion+'/ALL',
                'text':   'ALL', 'leaf': False, 'condType': 'Simulation',
                'configName': configName, 'configVersion': configVersion }
          d.update(dict.fromkeys(self.bkSimCondFields,''))
          d['simDesc']  ='ALL'
          d['simCondID']='999999'
          value.append(d)
      else:
        result = RPC.getSimulationConditions(configName,configVersion,1);
        if not result['OK']:
          return result
        vdict = {}
        for cond in result['Value']:
          if cond[0] in vdict:
            if cond != vdict[cond[0]]:
              return S_ERROR("Mismatch for %s" % str(cond[0]))
          else:
            vdict[cond[0]] = cond
        for cond in vdict.values():
          d = { 'id':     '/'+configName+'/'+configVersion+'/'+str(cond[0]),
                'text':   cond[1], 'leaf': False, 'condType': 'Run',
                'configName': configName, 'configVersion': configVersion }
          d.update(dict(zip(self.bkRunCondFields,cond)))
          d['DetectorCond'] = self.__runDetectorCond(d)
          value.append(d)
        if len(value):
          d = { 'id':     '/'+configName+'/'+configVersion+'/ALL',
                'text':   'ALL', 'leaf': False, 'condType': 'Run',
                'configName': configName, 'configVersion': configVersion }
          d.update(dict.fromkeys(self.bkRunCondFields,''))
          d['simCondID']='ALL'
          value.append(d)
      return {'OK': True, 'Value': value}
    result = self.__findSimCond(RPC,configName,configVersion,condType,simCondID)
    if not result['OK']:
      return result
    scd = result['Value']
    if not inProPass:
      result = RPC.getProPassWithSimCond(configName,configVersion,simCondID)
      if not result['OK']:
        return result
      ppd = {}
      for pp in result['Value']:
        if not pp[0] in ppd:
          ppd[pp[0]] = ''
      for pp in ppd:
        d = { 'id': '/'+configName+'/'+configVersion+'/'+simCondID+'/'+str(pp),
              'text': pp, 'leaf': False,
              'configName': configName, 'configVersion': configVersion,
              'inProPass': pp }
        d.update(scd)
        value.append(d);
      if len(value) and simCondID != 'ALL':
        d = { 'id': '/'+configName+'/'+configVersion+'/'+simCondID+'/ALL',
              'text': 'ALL', 'leaf': False,
              'configName': configName, 'configVersion': configVersion,
              'inProPass': 'ALL' }
        d.update(scd)
        value.append(d);
        
      return S_OK(value)
    if not evType:
      result = RPC.getEventTypeWithSimcond(configName,configVersion,simCondID,inProPass)
      if not result['OK']:
        return result
      for evt in result['Value']:
        d = { 'id': '/'+configName+'/'+configVersion+'/'+simCondID+'/'+inProPass+'/'+str(evt[0]),
              'text': "%s (%s)" % (str(evt[0]),str(evt[1])), 'leaf': False,
              'configName': configName, 'configVersion': configVersion,
              'inProPass': inProPass, 'evType': evt[0] }
        d.update(scd)
        value.append(d);
      return S_OK(value)
    if True:
      result = RPC.getFileTypesWithSimcond(configName,configVersion,simCondID,inProPass,evType,'ALL')
      if not result['OK']:
        return result
      for ftype in result['Value']:
        d = { 'id': '/'+configName+'/'+configVersion+'/'+simCondID+'/'+inProPass+'/'+evType+'/'+str(ftype[0]),
              'text': str(ftype[0]), 'leaf': True,
              'configName': configName, 'configVersion': configVersion,
              'inProPass': inProPass, 'evType': evType, 'inFileType': ftype[0] }
        d.update(scd)
        value.append(d);
      return S_OK(value)
    return {'OK': False, 'Message': 'Not implemented'}

  @jsonify
  def bkk_simcond(self):
    RPC = getRPCClient('Bookkeeping/BookkeepingManager')
    result = RPC.getSimConditions();
    if not result['OK']:
      return result
    rdict = result['Value']
    rows  = []
    for sc in result['Value']:
      rows.append(dict(zip(self.bkSimCondFields,sc)))
#    !!! Sorting and selection must be moved to MySQL/Service side
    return SelectAndSort(rows,'simCondID')

  @jsonify
  def soft_versions(self):
    addempty    = 'addempty' in request.params
    name        = str(request.params.get('name',''))
    webname     = str(request.params.get('webname',''))
    add         = str(request.params.get('add',''))
    if not name:
      return S_ERROR('No software name specified')
    result = getSoftVersions(name,webname,add)
    if not result['OK']:
      return result
    vers = []
    if addempty:
      vers.append({'v':'&nbsp;'})
    for x in result['Value']:
      vers.append({'v':x})
    return { 'OK':True, 'result':vers, 'total':len(vers) }

  def __steps_convert_old(self,steps):
    """ Convert the list of step definitions to internal form

        ??? AZ: I don't understand why we need this all... ???
        1) appX&appX is replaced by appX
        2) app-Ver/dbVer is replaced by app-Ver and dbVer appended
           to the list (once)
        3) sum of steps ( 'app1,app2,app3... (dbVer)' ) is appended
           to the list
    """
    ret = []
    dbver = ''
    all = ''
    for x in steps:
      if x == None:
        ret.append('')
        continue
      appl = x.split('&')
      if len(appl) > 1:
        if len(appl) > 2:
          return S_ERROR('Got unrecognized App spec %s' % x)
        if appl[0] != appl[1]:
          return S_ERROR('Got not equal apps is step %s' % x)
        x = appl[0] # leave only one... (why it can be more ???)
      appl = x.split('/')
      if len(appl) > 1 and appl[1] != '':
        if dbver and appl[1] != dbver:
          return S_ERROR('Got different DB versions is pass %s' % x)
        dbver = appl[1]
      x     = appl[0]
      if all == '':
        all = x
      else:
        all = all + ',%s' % x
      ret.append(x)
    if dbver:
      all = all + ' (%s)' % dbver
    ret.append(dbver)
    ret.append(all)
    return S_OK(ret)

  # passidx: 7x (AppName AppVer OptionFiles DDDb condDb)

  def __steps2pp(self,steps):
    """ Convert IDX form to PP form... !!! Why the are different ??? """
    ret = []
    i = 2
    stlen = len(steps)
    while i+6 <= stlen:
      step = steps[i:i+6]
      if not step[0]:
        ret.append(None)
      else:
        ret.append("%s %s/%s/%s/%s/%s" % step)
      i += 6
    return ret    

  def __step2label(self,step):
    """ App-Version form (for labels) """
    if not step[0]:
      return ''
    if step[1]:
      return '%s-%s' % step[0:2]
    return str(step[0])

  def __step2html(self,step):
    """ HTML form (for details) """
    s = self.__step2label(step)
    if not s:
      return s
    if step[2]:
      s += '<br>&nbsp;&nbsp;Options: %s' % step[2]
    if step[3]:
      s += '<br>&nbsp;&nbsp;DDDb: %s' % step[3]
    if step[4]:
      s += '<br>&nbsp;&nbsp;condDb: %s' % step[4]
    if step[5]:
      s += '<br>&nbsp;&nbsp;extraPackages: %s' % step[5]
    return s

  def __idx_steps_convert(self,steps):
    """ Convert the list of step definitions to internal form """
    ret = []
    all = ''
    i = 2
    stlen = len(steps)
    while i+6 <= stlen:
      x = steps[i:i+6]
      if not x[0]:
        break
      label = self.__step2label(x)
      html  = self.__step2html(x)
      ret.append( [label,html] + list(x) )
      all += ",%s" % label
      i += 6
    all = all[1:] # remove first ','
    for x in steps[i:]:
      if x:
        return S_ERROR('Skipped steps are not supported')
    while len(ret) < 7:
      ret.append(['',''])
    return S_OK([all,ret])

  @jsonify
  def bkk_passidx(self):
    reqType       = str(request.params.get('reqType',''))
    RPC = getRPCClient('Bookkeeping/BookkeepingManager')
    result = RPC.getPass_index();
    if not result['OK']:
      return result
    rows  = []
    for pas in result['Value']:
      ret = self.__idx_steps_convert(pas)
      if not ret['OK']:
        return ret
      passAll,pl = ret['Value']
      if reqType=='Simulation' and len(pl[0])>2 and pl[0][2] != 'Gauss':
        continue
      if reqType=='Reconstruction' and len(pl[0])>2 and pl[0][2] != 'Brunel':
        continue
      if reqType=='Stripping' and len(pl[0])>2 and pl[0][2] != 'DaVinci':
        continue
      row = { 'pID': pas[0], 'pDsc': pas[1], 'pAll': passAll }
      for i in range(0,7):
        if not pl[i][0]:
          break
        row['p%dLbl' % (i+1)] = pl[i][0]
        row['p%dHtml' % (i+1)]= pl[i][1]
        row['p%dApp' % (i+1)] = pl[i][2]
        row['p%dVer' % (i+1)] = pl[i][3]
        row['p%dOpt' % (i+1)] = pl[i][4]
        row['p%dDDDb' % (i+1)]= pl[i][5]
        row['p%dCDb' % (i+1)] = pl[i][6]
        row['p%dEP'  % (i+1)] = pl[i][7]
      rows.append(row)
#    !!! Sorting and selection must be moved to MySQL/Service side
    return SelectAndSort(rows,'pDsc')

  def __get_last_pass(self,total):
    ppd = total.split(' + ')
    if len(ppd) > 1:
      return ppd[-1]
    else:
      return ppd[0]

  @jsonify
  def bkk_pass_tree(self):
    configName    = str(request.params.get('configName', ''))
    configVersion = str(request.params.get('configVersion', ''))
    simCondID     = str(request.params.get('simCondID',''))
    passTotal     = str(request.params.get('passTotal',''))
    reqType       = str(request.params.get('reqType',''))

    RPC = getRPCClient('Bookkeeping/BookkeepingManager')
    value = []
    if not configName:
      result = RPC.getAvailableConfigurations();
      if not result['OK']:
        return result
      if not configName:
        known = {}
        for pair in result['Value']:
          name = pair[0]
          if not name in known:
            value.append({
              'id':         '/'+name,
              'text':       name,
              'configName': name
              })
            known[name] = True
      return {'OK': True, 'Value': value}
    if not configVersion:
      result = RPC.getAvailableConfigurations();
      if not result['OK']:
        return result
      for pair in result['Value']:
        name = pair[0]
        if name == configName:
          version = pair[1]
          value.append({
            'id':     '/'+name+'/'+version,
            'text':   version,
            'configName': name,
            'configVersion': version,
            })
      return {'OK': True, 'Value': value}
    if not simCondID:
      result = RPC.getSimulationConditions(configName,configVersion,0);
      if not result['OK']:
        return result
      for cond in result['Value']:
        value.append({
          'id':     '/'+configName+'/'+configVersion+'/'+str(cond[0]),
          'text':   cond[1],
          'configName': configName,
          'configVersion': configVersion,
          'simCondID': cond[0],
          })
      return {'OK': True, 'Value': value}

    if True:
      result = RPC.getProPassWithSimCond(configName,configVersion,simCondID);
      if not result['OK']:
        return result
      # ??? Is there better way to find index ?
      pplist = RPC.getPass_index();
      if not pplist['OK']:
        return pplist
      pplist  = pplist['Value']
      groups = {}
      for pp in result['Value']:
        if pp[0] in groups:
          groups[pp[0]] += 1
        else:
          groups[pp[0]] = 1
      for pp in result['Value']:
        if passTotal and pp[0] != passTotal:
          continue
        if groups[pp[0]] == 0: # was already inserted
          continue
        if not passTotal and groups[pp[0]] > 1:
          groups[pp[0]] = 0 # forget it
          value.append({
            'id':     '/'+configName+'/'+configVersion+'/'+\
            str(simCondID)+'/'+pp[0],
            'text':   pp[0],
            'configName': configName,
            'configVersion': configVersion,
            'simCondID': simCondID,
            'passTotal': pp[0],
            })
          continue
        ppdesc = self.__get_last_pass(pp[0])
        ppid = ''
        testlist = []
        for pi in pplist:
          if pi[1] == ppdesc:
            testlist.append(self.__steps2pp(pi))
          if pi[1] == ppdesc and self.__steps2pp(pi) == list(pp[1:]):
            ppid = pi[0]
            break
        if ppid == '':
          return S_ERROR('Unregistered Processing Pass %s' % str(pp))
        ret = self.__idx_steps_convert(pi)
        if not ret['OK']:
          return ret
        passAll,pl = ret['Value']
        if reqType=='Simulation' and len(pl[0])>2 and pl[0][2] != 'Gauss':
          continue
        if passTotal:
          path = str(pp[0])+'/'+str(ppid)
          text = passAll
        else:
          path = str(pp[0])
          text = str(pp[0])
        row = {
          'id':     '/'+configName+'/'+configVersion+'/'+\
                    str(simCondID)+'/'+path,
          'text':   text,
          'configName': configName,
          'configVersion': configVersion,
          'simCondID': simCondID,
          'passTotal': pp[0],
          'pID': ppid,
          'pDsc': ppdesc,
          'pAll' : passAll,
          'leaf': True
          };
        for i in range(0,7):
          if not pl[i][0]:
            break
          row['p%dLbl' % (i+1)] = pl[i][0]
          row['p%dHtml' % (i+1)]= pl[i][1]
          row['p%dApp' % (i+1)] = pl[i][2]
          row['p%dVer' % (i+1)] = pl[i][3]
          row['p%dOpt' % (i+1)] = pl[i][4]
          row['p%dDDDb' % (i+1)]= pl[i][5]
          row['p%dCDb' % (i+1)] = pl[i][6]
          row['p%dEP'  % (i+1)] = pl[i][7]
        value.append(row)
      return {'OK': True, 'Value': value}

    return {'OK': False, 'Message': 'Not implemented'}

  @jsonify
  def bkk_event_types(self):
    addempty    = 'addempty' in request.params
    RPC = getRPCClient('Bookkeeping/BookkeepingManager')
    result = RPC.getAvailableEventTypes();
    if not result['OK']:
      return result
    rows  = []
    for et in result['Value']:
      rows.append({
        'id': et[0],
        'name': et[1],
        'text': '%s - %s' % (str(et[0]),str(et[1]))
        })
    rows.sort(key=lambda x: x['id'])
    if addempty:
      rows.insert(0,{'id':99999999, 'name': '', 'text':'&nbsp;'})
    return { 'OK':True, 'result':rows, 'total':len(rows) }    

  @jsonify
  def progress(self):
    id  = str(request.params.get('RequestID', ''))
    try:
      id = long(id);
    except Exception, e:
      return S_ERROR('Reqiest ID is not a number')
    return self.engine.getProductionProgressList(id);

  @jsonify
  def add_production(self):
    rdict = dict(request.params)
    try:
      requestID = long(rdict['RequestID'])
      productionID = long(rdict['ProductionID'])
    except:
      return S_ERROR('Incorrect Reqiest or production ID')
    result = bkProductionProgress(productionID)
    if not result['OK']:
      bkEvents = 0
    else:
      bkEvents = result['Value']
    return self.engine.addProduction({
      'ProductionID':productionID,'RequestID':requestID,
      'Used':1,'BkEvents':bkEvents
      })

  @jsonify
  def remove_production(self):
    rdict = dict(request.params)
    try:
      productionID = long(rdict['ProductionID'])
    except:
      return S_ERROR('Production ID is not a number')
    return self.engine.removeProduction(productionID)

  @jsonify
  def use_production(self):
    rdict = dict(request.params)
    used = rdict.get('Used',True)
    if str(used) == 'false':
      used = False
    try:
      productionID = long(rdict['ProductionID'])
      used         = bool(used)
    except:
      return S_ERROR('Incorrect Production ID use Used flag')
    return self.engine.useProduction(productionID,used)

  @jsonify
  def history(self):
    id  = str(request.params.get('RequestID', ''))
    try:
      id = long(id);
    except Exception, e:
      return S_ERROR('Reqiest ID is not a number')
    return self.engine.getRequestHistory(id);

  @jsonify
  def getRequest(self):
    id  = str(request.params.get('RequestID', ''))
    try:
      id = long(id);
    except Exception, e:
      return S_ERROR('Reqiest ID is not a number')
    return self.engine.getProductionRequest([id]);

  @jsonify
  def templates(self):
    return self.engine.templates()

  def __getTemplate(self,name):
    return self.engine.getTemplate(name)

  @jsonify
  def template_parlist(self):
    tpl_name  = str(request.params.get('tpl', ''))
    result = self.__getTemplate(tpl_name)
    if not result['OK']:
      return result
    text = result['Value']
    result = self.__getTemplate(tpl_name+'_run.py')
    if result['OK']:
      text += result['Value']
    tpl = PrTpl(text)
    rqf = self.engine.getRequestFields()
    tpf = tpl.getParams()
    plist = []
    for x in tpf:
      if not x in rqf:
        plist.append({'par':x, 'label':tpf[x], 'value':""})
    return { 'OK':True, 'total': len(plist), 'result': plist }

  @jsonify
  def create_workflow(self):
    """ !!! Note: 1 level parent=master assumed !!! """
    rdict = dict(request.params)
    for x in ['RequestID','Template','Subrequests']:
      if not x in rdict:
        return S_ERROR('Required parameter %s is not specified' % x)
    try:
      id       = long(rdict['RequestID'])
      tpl_name = str(request.params['Template'])
      sstr  = str(request.params['Subrequests'])
      if sstr:
        slist = [long(x) for x in sstr.split(',')]
      else:
        slist = []
      sdict = dict.fromkeys(slist,None)
      del rdict['RequestID']
      del rdict['Template']
      del rdict['Subrequests']
    except Exception, e:
      return S_ERROR('Wrong parameters (%s)' % str(e))

    ret = self.__getTemplate(tpl_name)
    if not ret['OK']:
      return ret
    tpl = PrTpl(ret['Value'])
    run_tpl = None
    ret = self.__getTemplate(tpl_name+'_run.py')
    if ret['OK']:
      run_tpl = PrTpl(ret['Value'])
      
    ret = self.engine.getProductionRequest([id])
    if not ret['OK']:
      return ret
    rqdict  = ret['Value'][id]
    
    dictlist = []
    if rqdict['_is_leaf']:
      d = self.engine.getRequestFields()
      d.update(rqdict)
      d.update(rdict)
      dictlist.append(d)
    else:
      if not len(sdict):
        return S_ERROR('Subrequests are not specified (but required)')
      ret = self.engine.getProductionRequestList(id)
      if not ret['OK']:
        return ret
      for x in ret['result']:
        if not x['ID'] in sdict:
          continue
        d = self.engine.getRequestFields()
        d.update(rqdict)
        for y in x:
          if x[y]:
            d[y]=x[y]
        d.update(rdict)
        dictlist.append(d)
    success = []
    fail = []
    RPC = getRPCClient("ProductionManagement/ProductionRequest")
    for x in dictlist:
      for y in x:
        if x[y] == None:
          x[y] = ''
        else:
          x[y] = str(x[y])
      if not run_tpl:
        success.append({ 'ID': x['ID'], 'Body': tpl.apply(x)})
      else:
        res = RPC.execProductionScript(run_tpl.apply(x),tpl.apply(x))
        if res['OK']:
          success.append({ 'ID': x['ID'], 'Body':  res['Value'] })
        else:
          fail.append(str(x['ID']))
      continue # not working with WF DB for now    
      name = 'PRQ_%s' % x['ID']
      wf = fromXMLString(tpl.apply(x))
      wf.setName(name)
      wf.setType('production/requests')
      try:
        wfxml = wf.toXML()
        result = RPC.publishWorkflow(str(wfxml),True)
      except Exception,msg:
        result = {'OK':False, 'Message': str(msg)}
      if not result['OK']:
        fail.append(str(x['ID']))
      else:
        success.append(str(x['ID']))

    if len(fail):
      return S_ERROR("Couldn't create workflows for %s." \
                     % (','.join(fail)))
    else:
      # return S_OK("Success with %s" % ','.join(success))
      return S_OK(success)

  def request_parameters(self):
    """ !!! Note: 1 level parent=master assumed !!! """
    id  = str(request.params.get('RequestID', ''))
    try:
      id = long(id);
    except Exception, e:
      return S_ERROR('Reqiest ID is not a number')
    d = self.engine.getRequestFields()

    ret = self.engine.getProductionRequest([id])
    if not ret['OK']:
      return ret
    rqdict  = ret['Value'][id]
    master = rqdict['_master']
    if master:
      ret = self.engine.getProductionRequest([master])
      if not ret['OK']:
        return ret
      d.update(ret['Value'][master])
    for x in rqdict:
      if rqdict[x]:
        d[x]=rqdict[x]
    for x in d:
      if d[x] == None:
        d[x] = ''
      else:
        d[x] = str(d[x])
    response.headers['Content-type'] = "text/html"
    html = "<html>\n<body>\n<H1>Parameters for request %s</H1>\n" % id
    html+= "<TABLE border=\"1\" width=\"100%\">\n"
    for x in sorted(d.keys()):
      html+= "<TR><TD>%s<TD>%s</TR>\n" % (x,d[x])
    html+= "</TABLE>\n</body>\n</html>"
    return html
