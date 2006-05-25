# mysql.py
# Copyright (C) 2005,2006 Michael Bayer mike_mp@zzzcomputing.com
#
# This module is part of SQLAlchemy and is released under
# the MIT License: http://www.opensource.org/licenses/mit-license.php

import sys, StringIO, string, types, re, datetime

from sqlalchemy import sql,engine,schema,ansisql
from sqlalchemy.engine import default
import sqlalchemy.types as sqltypes
import sqlalchemy.databases.information_schema as ischema
import sqlalchemy.exceptions as exceptions

try:
    import MySQLdb as mysql
except:
    mysql = None
    
class MSNumeric(sqltypes.Numeric):
    def get_col_spec(self):
        return "NUMERIC(%(precision)s, %(length)s)" % {'precision': self.precision, 'length' : self.length}
class MSDouble(sqltypes.Numeric):
    def __init__(self, precision = None, length = None):
        if (precision is None and length is not None) or (precision is not None and length is None):
            raise exceptions.ArgumentError("You must specify both precision and length or omit both altogether.")
        super(MSDouble, self).__init__(precision, length)
    def get_col_spec(self):
        if self.precision is not None and self.length is not None:
            return "DOUBLE(%(precision)s, %(length)s)" % {'precision': self.precision, 'length' : self.length}
        else:
            return "DOUBLE"
class MSFloat(sqltypes.Float):
    def __init__(self, precision = None):
        super(MSFloat, self).__init__(precision)
    def get_col_spec(self):
        if self.precision is not None:
            return "FLOAT(%(precision)s)" % {'precision': self.precision}
        else:
            return "FLOAT"
class MSInteger(sqltypes.Integer):
    def get_col_spec(self):
        return "INTEGER"
class MSSmallInteger(sqltypes.Smallinteger):
    def get_col_spec(self):
        return "SMALLINT"
class MSDateTime(sqltypes.DateTime):
    def get_col_spec(self):
        return "DATETIME"
class MSDate(sqltypes.Date):
    def get_col_spec(self):
        return "DATE"
class MSTime(sqltypes.Time):
    def get_col_spec(self):
        return "TIME"
    def convert_result_value(self, value, dialect):
        # convert from a timedelta value
        if value is not None:
            return datetime.time(value.seconds/60/60, value.seconds/60%60, value.seconds - (value.seconds/60*60))
        else:
            return None
            
class MSText(sqltypes.TEXT):
    def get_col_spec(self):
        return "TEXT"
class MSString(sqltypes.String):
    def get_col_spec(self):
        return "VARCHAR(%(length)s)" % {'length' : self.length}
class MSChar(sqltypes.CHAR):
    def get_col_spec(self):
        return "CHAR(%(length)s)" % {'length' : self.length}
class MSBinary(sqltypes.Binary):
    def get_col_spec(self):
        if self.length is not None and self.length <=255:
            # the binary type seems to return a value that is null-padded
            return "BINARY(%d)" % self.length
        else:
            return "BLOB"
    def convert_result_value(self, value, engine):
        if value is None:
            return None
        else:
            return buffer(value)

class MSBoolean(sqltypes.Boolean):
    def get_col_spec(self):
        return "BOOLEAN"
        
colspecs = {
    sqltypes.Integer : MSInteger,
    sqltypes.Smallinteger : MSSmallInteger,
    sqltypes.Numeric : MSNumeric,
    sqltypes.Float : MSFloat,
    sqltypes.DateTime : MSDateTime,
    sqltypes.Date : MSDate,
    sqltypes.Time : MSTime,
    sqltypes.String : MSString,
    sqltypes.Binary : MSBinary,
    sqltypes.Boolean : MSBoolean,
    sqltypes.TEXT : MSText,
    sqltypes.CHAR: MSChar,
}

ischema_names = {
    'int' : MSInteger,
    'smallint' : MSSmallInteger,
    'tinyint' : MSSmallInteger, 
    'varchar' : MSString,
    'char' : MSChar,
    'text' : MSText,
    'decimal' : MSNumeric,
    'float' : MSFloat,
    'double' : MSDouble,
    'timestamp' : MSDateTime,
    'datetime' : MSDateTime,
    'date' : MSDate,
    'time' : MSTime,
    'binary' : MSBinary,
    'blob' : MSBinary,
}

def engine(opts, **params):
    return MySQLEngine(opts, **params)

def descriptor():
    return {'name':'mysql',
    'description':'MySQL',
    'arguments':[
        ('username',"Database Username",None),
        ('password',"Database Password",None),
        ('database',"Database Name",None),
        ('host',"Hostname", None),
    ]}


class MySQLExecutionContext(default.DefaultExecutionContext):
    def post_exec(self, engine, proxy, compiled, parameters, **kwargs):
        if getattr(compiled, "isinsert", False):
            self._last_inserted_ids = [proxy().lastrowid]

class MySQLDialect(ansisql.ANSIDialect):
    def __init__(self, module = None, **kwargs):
        if module is None:
            self.module = mysql
        ansisql.ANSIDialect.__init__(self, **kwargs)

    def create_connect_args(self, url):
        opts = url.translate_connect_args(['host', 'db', 'user', 'passwd', 'port'])
        return [[], opts]

    def create_execution_context(self):
        return MySQLExecutionContext(self)

    def type_descriptor(self, typeobj):
        return sqltypes.adapt_type(typeobj, colspecs)

    def supports_sane_rowcount(self):
        return False

    def compiler(self, statement, bindparams, **kwargs):
        return MySQLCompiler(self, statement, bindparams, **kwargs)

    def schemagenerator(self, *args, **kwargs):
        return MySQLSchemaGenerator(*args, **kwargs)

    def schemadropper(self, *args, **kwargs):
        return MySQLSchemaDropper(*args, **kwargs)

    def get_default_schema_name(self):
        if not hasattr(self, '_default_schema_name'):
            self._default_schema_name = text("select database()", self).scalar()
        return self._default_schema_name
    
    def dbapi(self):
        return self.module

    def has_table(self, connection, table_name):
        cursor = connection.execute("show table status like '" + table_name + "'")
        return bool( not not cursor.rowcount )

    def reflecttable(self, connection, table):
        # to use information_schema:
        #ischema.reflecttable(self, table, ischema_names, use_mysql=True)
        
        tabletype, foreignkeyD = self.moretableinfo(connection, table=table)
        table.kwargs['mysql_engine'] = tabletype
        
        c = connection.execute("describe " + table.name, {})
        while True:
            row = c.fetchone()
            if row is None:
                break
            #print "row! " + repr(row)
            (name, type, nullable, primary_key, default) = (row[0], row[1], row[2] == 'YES', row[3] == 'PRI', row[4])
            
            match = re.match(r'(\w+)(\(.*?\))?', type)
            coltype = match.group(1)
            args = match.group(2)
            
            #print "coltype: " + repr(coltype) + " args: " + repr(args)
            coltype = ischema_names.get(coltype, MSString)
            if args is not None:
                args = re.findall(r'(\d+)', args)
                #print "args! " +repr(args)
                coltype = coltype(*[int(a) for a in args])
            
            arglist = []
            fkey = foreignkeyD.get(name)
            if fkey is not None:
                arglist.append(schema.ForeignKey(fkey))
    
            table.append_item(schema.Column(name, coltype, *arglist,
                                            **dict(primary_key=primary_key,
                                                   nullable=nullable,
                                                   default=default
                                                   )))
    
    def moretableinfo(self, connection, table):
        """Return (tabletype, {colname:foreignkey,...})
        execute(SHOW CREATE TABLE child) =>
        CREATE TABLE `child` (
        `id` int(11) default NULL,
        `parent_id` int(11) default NULL,
        KEY `par_ind` (`parent_id`),
        CONSTRAINT `child_ibfk_1` FOREIGN KEY (`parent_id`) REFERENCES `parent` (`id`) ON DELETE CASCADE\n) TYPE=InnoDB
        """
        c = connection.execute("SHOW CREATE TABLE " + table.name, {})
        desc = c.fetchone()[1].strip()
        tabletype = ''
        lastparen = re.search(r'\)[^\)]*\Z', desc)
        if lastparen:
            match = re.search(r'\b(?:TYPE|ENGINE)=(?P<ttype>.+)\b', desc[lastparen.start():], re.I)
            if match:
                tabletype = match.group('ttype')
        foreignkeyD = {}
        fkpat = (r'FOREIGN KEY\s*\(`?(?P<name>.+?)`?\)'
                 r'\s*REFERENCES\s*`?(?P<reftable>.+?)`?'
                 r'\s*\(`?(?P<refcol>.+?)`?\)'
                )
        for match in re.finditer(fkpat, desc):
            foreignkeyD[match.group('name')] = match.group('reftable') + '.' + match.group('refcol')

        return (tabletype, foreignkeyD)
        

class MySQLCompiler(ansisql.ANSICompiler):

    def limit_clause(self, select):
        text = ""
        if select.limit is not None:
            text +=  " \n LIMIT " + str(select.limit)
        if select.offset is not None:
            if select.limit is None:
                # striaght from the MySQL docs, I kid you not
                text += " \n LIMIT 18446744073709551615"
            text += " OFFSET " + str(select.offset)
        return text
        
class MySQLSchemaGenerator(ansisql.ANSISchemaGenerator):
    def get_column_specification(self, column, override_pk=False, first_pk=False):
        colspec = column.name + " " + column.type.engine_impl(self.engine).get_col_spec()
        default = self.get_column_default_string(column)
        if default is not None:
            colspec += " DEFAULT " + default

        if not column.nullable:
            colspec += " NOT NULL"
        if column.primary_key:
            if not override_pk:
                colspec += " PRIMARY KEY"
            if not column.foreign_key and first_pk and isinstance(column.type, sqltypes.Integer):
                colspec += " AUTO_INCREMENT"
        if column.foreign_key:
            colspec += ", FOREIGN KEY (%s) REFERENCES %s(%s)" % (column.name, column.foreign_key.column.table.name, column.foreign_key.column.name) 
        return colspec

    def post_create_table(self, table):
        mysql_engine = table.kwargs.get('mysql_engine', None)
        if mysql_engine is not None:
            return " TYPE=%s" % mysql_engine
        else:
            return ""

class MySQLSchemaDropper(ansisql.ANSISchemaDropper):
    def visit_index(self, index):
        self.append("\nDROP INDEX " + index.name + " ON " + index.table.name)
        self.execute()

dialect = MySQLDialect