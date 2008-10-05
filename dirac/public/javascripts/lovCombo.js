Ext.ns('Ext.ux.form');
Ext.ux.form.LovCombo = Ext.extend(Ext.form.ComboBox, {
    checkField:'checked'
    ,separator:':::'
    ,initComponent:function() {
		if(!this.tpl) {
			this.tpl = 
				 '<tpl for=".">'
				+'<div class="x-combo-list-item">'
				+'<img src="' + Ext.BLANK_IMAGE_URL + '" '
				+'class="ux-lovcombo-icon ux-lovcombo-icon-'
				+'{[values.' + this.checkField + '?"checked":"unchecked"' + ']}">'
				+'<div class="ux-lovcombo-item-text">{' + this.displayField + '}</div>'
				+'</div>'
				+'</tpl>'
			;
		}
        Ext.ux.form.LovCombo.superclass.initComponent.apply(this, arguments);
		this.on({
			 scope:this
			,beforequery:this.onBeforeQuery
			,blur:this.onRealBlur
		});
		this.onLoad = this.onLoad.createSequence(function() {
			if(this.el) {
				var v = this.el.dom.value;
				this.el.dom.value = '';
				this.el.dom.value = v;
			}
		});
    } // e/o function initComponent
	,initEvents:function() {
		Ext.ux.form.LovCombo.superclass.initEvents.apply(this, arguments);
		this.keyNav.tab = false;
	} // eo function initEvents
	,clearValue:function() {
		this.value = '';
		this.setRawValue(this.value);
		this.store.clearFilter();
		this.store.each(function(r) {
			r.set(this.checkField, false);
		}, this);
		if(this.hiddenField) {
			this.hiddenField.value = '';
		}
	} // eo function clearValue
	,getCheckedDisplay:function() {
		var re = new RegExp(this.separator, "g");
		return this.getCheckedValue(this.displayField).replace(re, this.separator + ' ');
	} // eo function getCheckedDisplay
	,getCheckedValue:function(field) {
		field = field || this.valueField;
		var c = [];
		var snapshot = this.store.snapshot || this.store.data;
		snapshot.each(function(r) {
			if(r.get(this.checkField)) {
				c.push(r.get(field));
			}
		}, this);
		return c.join(this.separator);
	} // eo function getCheckedValue
	,onBeforeQuery:function(qe) {
		qe.query = qe.query.replace(new RegExp(this.getCheckedDisplay() + '[ ' + this.separator + ']*'), '');
	} // eo function onBeforeQuery
	,onRealBlur:function() {
		this.list.hide();
		var v = this.getRawValue();
		var va = [];
                if(v == ''){
                  this.clearValue();
                }
		this.store.clearFilter();
		this.store.each(function(r) {
			var re = new RegExp(r.get(this.displayField).replace(/\(s\)/,''));
			if(v.match(re)) {
				re = r.get(this.displayField);
				newV = v.splie(',');
				for(var s = 0; s < newV.length; s++){
					if(re == newV[s]){
						va.push(r.get(this.valueField));
					}
				}
			}
		}, this);
		this.setValue(va.join(this.separator));
	} // eo function onRealBlur
	,onSelect:function(record, index) {
        	if(this.fireEvent('beforeselect', this, record, index) !== false){
			record.set(this.checkField, !record.get(this.checkField));
			if(index == 0){
				var fItem = this.store.data.items[0].json[1];
				if(fItem == 'All'){
					var total = this.store.totalLength;
					for(var k = 0; k < total; k++) {
						this.store.data.items[k].set(this.checkField, record.get(this.checkField));
					}
					this.setValue(this.getCheckedValue());
				}else{
					this.setValue(this.getCheckedValue());
					this.fireEvent('select', this, record, index);
				}
			}else{
                	        this.setValue(this.getCheckedValue());
            			this.fireEvent('select', this, record, index);
			}
		}
	} // eo function onSelect
	,setValue:function(v) {
		if(v) {
			v = '' + v;
			if(this.valueField) {
				this.store.clearFilter();
				this.store.each(function(r) {
					var checked = !(!v.match(
						 '(^|' + this.separator + ')' + r.get(this.valueField) 
						+'(' + this.separator + '|$)'))
					;
					r.set(this.checkField, checked);
				}, this);
				this.value = this.getCheckedValue();
                               	this.displayValue = this.getCheckedDisplay();
				this.displayValue = this.displayValue.replace(/:::/g,',');
				this.displayValue = this.displayValue.replace(/All, /g,'');
				this.setRawValue(this.displayValue);
				if(this.hiddenField) {
					this.hiddenField.value = this.getCheckedDisplay();
				}
			} else {
				this.value = v;
				this.setRawValue(v);
				if(this.hiddenField) {
					this.hiddenField.value = v;
				}
			}
		} else {
			this.clearValue();
		}
	} // eo function setValue
}); // eo extend
Ext.reg('lovcombo', Ext.ux.form.LovCombo); 
