# -*- coding: utf-8 -*-

<%
from DIRAC import gConfig
numFields = 6
%>
<%inherit file="/base.mako" />
<%namespace file="/systems/monitoring/renderView.mako" name="renderView"/>

<%def name="head_tags()">
${renderView.head_tags()}
<style>
 div#loading
 {
 	height : 30px;
 	width : auto;
 	vertical-align : top;
 	visibility : hidden;
 	padding : 5px;
 }
 div#loading img
 {
 	height : 20px;
 	width : auto;
 }

 table.field {
 	width : 250px;
 	display : inline;
 }
 table.field td{
 	padding : 5px 2px 0px 0px;
 }
 div.imgContainer {
 	width : 97%;
 }


 table.pageSchema {
  margin-left : auto;
  margin-right : auto;
 }
 table.pageSchema td.commands {
  vertical-align : top;
  padding : 0% 5% 0% 5%;
 }
 ul.commands {
  border : 1px solid #AAA;
  background : #EEE;
  text-align : right;
  padding : 5%;
 }

 table.views td{
 	border : 1px solid black;
 	padding : 5px;
 }

 table.views th{
 	font-weight : bold;
 	padding : 5px;
 	text-align : center;
 }

 div.plotContainer
 {
 	margin-top : 20px;
 }
</style>
<script>
 function initRadioButton()
 {
 	radioObj = document.plotsForm.selectView;
	for( var i = 0; i< radioObj.length; i++ )
	{
		radioObj[ i ].checked = false;
	}
 };
 YAHOO.util.Event.onContentReady( 'plotsFormId', initRadioButton );
</script>
</%def>

<h2>Plot monitoring views</h2>

<form id='plotsFormId' name='plotsForm'>
<table class='pageSchema'>
 <tr>
  <td>
   <table class='views'>
    <tr>
     <th>Select</th>
     <th>View</th>
    </tr>
%for i in range( len( c.viewsList ) ):
%if len( c.viewsList[i][2] ) == 0:
    <tr>
     <td><input type='radio' name='selectView' value='${c.viewsList[i][0]}' onchange='javascript:setMonitoringViewId("${c.viewsList[i][1]}")'/></td>
     <td><a href='#' onclick='javascript:setMonitoringViewId("${c.viewsList[i][1]}")'>${c.viewsList[i][1]}</a></td>
    <tr>
%endif
%endfor
   </table>
  </td>
  </td>
 </tr>
</table>
</form>

<div class='plotContainer'>
${renderView.monitoringViewAnchor( False )}
</div>