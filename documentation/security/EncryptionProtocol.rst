Encryption Protocol
===================
GlobaLeaks implements an encryption protocol specifically designed for anonymous whistleblowing applications.

The protocol has been developed and validated in collaboration with the [Open Technology Fund](https://www.opentech.fund/results/supported-projects/globaleaks/) and represents a tradeoff between security and usability intended to provide easy use by whistleblowers and reasonable security from attackers seizing the backend and attempting bruteforce decryption.

Encryption is implemented for each submission protecting questionnaire's answers, comments, attachments and involved metadata. The keys involved in the encryption are per-user and per-submission and only users to which the data was destinated could access the data. This mechanism guarantees that only the user could access the data. Users that would forget their password would lose access to data that won’t be accessible anymore. To handle with this condition the system implements as well `Key recovery`_ and `Key Escrow`_ mechanisms.

Encryption's Workflow
#####################
* Users chooses a personal secure password at first login;
* The system creates a personal user keypair and stores it asymmetrically encrypted with a secret derived from the personal user password;
* The whistleblower files a report;
* The system assigns personal access credentials to the whistleblower;
* The system generates a symmetric key for the encryption of the report, the attached files and comments and the involved metadata and starts encrypting the data;
* The system generates an asymmetric keypair and store it symmetrically encrypted using a secret derived from the whistleblower access credentials;
* The system grants every involved recipient and the whistleblower access to the symmetric encryption key of the report by assigning each of the user an asymmetrically encrypted copy of the key;
* Users furtherly proceed exchanging information on the report by using their personal access credentials and unlocking their own personal asymmetric keys and symmetric keys of the accessed report.

Encryption's Details
####################
Algorithms
----------
.. csv-table::
   :header: "Type", "Implementation"

   "Asymmetric encryption", "`Libsodium SealedBoxes <https://pynacl.readthedocs.io/en/stable/public/#nacl.public.SealedBox>`_, an encryption implementation that combines Curve25519, XSalsa20 and Poly1305 alghoritms."
   "Symmetric encryption", "`Libsodium SecretBoxes <https://pynacl.readthedocs.io/en/stable/secret/#nacl.secret.SecretBox>`_, an encryption implementation that combines XSalsa20 and Poly1305."

Users’ Credentials
------------------
The system used two different type of credentials depending on the user role:

.. csv-table::
   :header: "Credentials type", "User role"

   "Passwords", "Passowrds are used for authenticating users identified by a username"
   "Receipts", "Receipts are 16-digits random secrets used for authenticating anonymous whistleblowers"

Assumptions:

* The system enforces strong password complexity;
* The system enforces expiration of receipts according to a strict data retention policy limiting the concurrent number of active receipts;

Users’ Keys
-----------

.. csv-table::
   :header: "Type", "Generation", "Storage"

   "ECC Curve25519 keypair", "Generated by the backend at first user login for authenticated users and on submission for whistleblowers", "Keys are stored on the backend encrypted using symmetric encryption. The symmetric key used for encrypting users’ keys is derived from the users’ credentials using the KDF function `Argon2ID <https://password-hashing.net/argon2-specs.pdf>`_. The parameters for Argon2ID used for KDF are chosen stronger than the parameters one used for authentication of related user which the hash is stored. The parameters are chosen to require 128MB per Login and 1 second of computation."

Data Encryption's Keys
----------------------

.. csv-table::
   :header: "Type", "Generation", "Storage"

   "256 bit keys", "Generated by the backend for each report", "Keys and stored on backend filesystem  encrypted using asymmetric encryption by means of Users’ and Whistleblower’s keys respectively"

Key Generation
##############
Users' encryption keys are automatically generated during the first user login and secured by means of the user passphrase used for login. This simple but effective key generation policy requires users to perform their first login before being enabled to receive reports.

Key Recovery
############
The system implements a key recovery system by means of a recovery key and symmetric encryption.

Upon generation of a user key, the private key is symmetrically encrypted with a randomly generated recovery key.

For usability reasons, this recovery is kept as well encrypted on the backend making it possible for logged users in possession of their password to retrieve and print their own account recovery key.

Key Escrow
##########
The system implements an optional key escrow mechanism in order to limit data loss in case of users’ password loss.

Key escrow can be enabled during the initial application wizard or alternatively could be enabled in the advanced settings of the software.

We advise enabling this option if you would like to protect whistleblowers' submissions from being lost in the situation where recipients lose their passwords. On the other hand, we would not advise using this feature if you want to setup a system where only recipients are able to access submissions.

When the option is enabled the system will generate and assign an escrow key and assign it to the administrator that has enabled the feature; the key will be furtherly used by the system to encrypt every system key preserving a copy that could be unlocked by any administrator in the availability of the escrow key.

Administrators with access to the escrow key will be able to support any internal user in case of password loss and issue password reset. As well they will be able to grant this same priviledge to other administrators or disable the feature completely.
